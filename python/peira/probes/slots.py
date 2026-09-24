"""Slot-substitution probe generation (stdlib-only).

A slot-substitution probe takes one case and produces *variants*: copies of
the case's inputs with slot values swapped for same-kind alternatives
(``"Acme Corp"`` -> ``"Globex Inc"``, ``"$50,000"`` -> ``"$47,500"``) while
the decision semantics stay fixed. An adapter that decides on substance
should return the same decision on every variant; one that memorized the
public case text stumbles on the surface changes. See
:mod:`peira.probes.invariance` for the flip-rate helper.

Design notes:

- Slots are *typed*: a name slot only ever takes a name, an amount slot
  only an amount. The substitution tables below are fixed and curated;
  nothing is fetched from the network or the filesystem.
- Generation is deterministic given ``(seed, index)``: each variant seeds
  its own ``random.Random``, so variant *k* of a case is reproducible
  forever. The seed travels on the variant record for the manifest.
- The attacked arm's *payload* is sacred. Spans where the attacked input
  differs from the benign input (via :mod:`difflib`) are never
  substituted: swapping the payload would change the attack mechanism and
  corrupt the case. Only the surrounding surface form varies.
- The same source string always maps to the same replacement within one
  variant, so repeated mentions stay consistent.
- Variants that end up with zero substitutions are omitted from the
  output: a byte-identical "variant" is not a probe.
- Slot *detection* for names/organizations is caller-declared
  (:class:`SlotSpec` with a regex); the generator is the mechanism, not
  an NER system. Money amounts, dates, and conservative synonym swaps are
  detected automatically and can be disabled per kind.
"""

from __future__ import annotations

import copy
import datetime
import difflib
import random
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Sequence

SLOT_KINDS = ("person", "org", "location", "product", "money", "date", "synonym")
_ARMS = ("benign", "attacked")

# Fixed, curated, deliberately fictitious substitution tables. ASCII only.
_PERSONS = (
    "Amara Okafor", "Jonas Weber", "Priya Natarajan", "Diego Fuentes",
    "Mei-Lin Chao", "Tariq Haddad", "Sofia Marchetti", "Kwame Mensah",
    "Ingrid Sorensen", "Rafael Duarte", "Yuki Tanaka", "Nadia Rahman",
)
_ORGS = (
    "Acme Corp", "Globex Inc", "Initech LLC", "Hooli Systems",
    "Vandelay Industries", "Starkwood Ltd", "Massive Dynamic",
    "Tyrell Corporation", "Soylent Company", "Umbrella Health",
)
_LOCATIONS = (
    "Springfield", "Riverton", "Lakeside", "Fairview", "Brookfield",
    "Milltown", "Oakdale", "Cedar Falls", "Maple Grove", "Elmhurst",
)
_PRODUCTS = (
    "Widget X200", "Gizmo Pro", "Sprocket 3000", "Anvil Deluxe",
    "Doohickey Plus", "Thingamajig 9", "Contraption S", "Gadget Mini",
)
_TABLES = {
    "person": _PERSONS,
    "org": _ORGS,
    "location": _LOCATIONS,
    "product": _PRODUCTS,
}

_MONEY_RE = re.compile(r"\$(\d[\d,]*(?:\.\d{2})?)")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_LONG_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December) (\d{1,2}), (\d{4})\b"
)
_MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5,
    "June": 6, "July": 7, "August": 8, "September": 9, "October": 10,
    "November": 11, "December": 12,
}

# Conservative synonym table: modifiers only, never nouns or verbs that
# could plausibly be decision labels in an open vocabulary. Callers with
# context knowledge can extend via ``extra_synonyms``; when in doubt,
# disable with ``synonyms=False``.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "quick": ("fast", "rapid"),
    "quickly": ("rapidly", "swiftly"),
    "large": ("big", "sizable"),
    "small": ("tiny", "little"),
    "often": ("frequently",),
    "nearly": ("almost",),
    "very": ("highly", "extremely"),
    "many": ("numerous",),
    "several": ("multiple",),
    "various": ("diverse", "assorted"),
}

_MONEY_FACTORS = [round(0.90 + 0.02 * i, 2) for i in range(11) if i != 5]
_DATE_OFFSETS = [d for d in range(-45, 46) if d != 0]


@dataclass(frozen=True)
class SlotSpec:
    """A caller-declared slot: the regex ``pattern``'s whole match is a
    slot of ``kind``, replaced with a same-kind alternative.

    Use this for entity kinds the automatic detectors cannot see (names,
    organizations, products): no stdlib NER exists, so the caller names
    the spans. ``kind`` must be one of :data:`SLOT_KINDS`.
    """

    kind: str
    pattern: str
    name: str = ""

    def __post_init__(self) -> None:
        if self.kind not in SLOT_KINDS:
            raise ValueError(
                f"unknown slot kind: {self.kind!r} "
                f"(expected one of {', '.join(SLOT_KINDS)})"
            )
        try:
            re.compile(self.pattern)
        except re.error as e:
            raise ValueError(f"bad slot pattern {self.pattern!r}: {e}") from e


@dataclass(frozen=True)
class Substitution:
    """One applied slot swap, for audit."""

    kind: str
    original: str
    replacement: str
    field: str  # dotted path within the arm input, e.g. "prompt"


@dataclass(frozen=True)
class ProbeVariant:
    """One slot-substituted variant of one arm of one case."""

    arm: str
    index: int
    seed: int
    input: dict[str, Any]
    substitutions: tuple[Substitution, ...] = ()


@dataclass
class _Match:
    start: int
    end: int
    kind: str
    priority: int  # lower wins on overlap: explicit (0) > money/date (1) > synonym (2)
    data: Any = None  # kind-specific payload (synonym alternatives)


def _iter_text_fields(obj: Any, path: str = ""):
    """Yield ``(dotted path, text)`` for every string in nested dicts/lists."""
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            child = f"{path}.{key}" if path else str(key)
            yield from _iter_text_fields(value, child)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            child = f"{path}.{i}" if path else str(i)
            yield from _iter_text_fields(value, child)
    elif isinstance(obj, str):
        yield path, obj


def _set_text_field(obj: dict[str, Any], path: str, value: str) -> None:
    node: Any = obj
    parts = path.split(".")
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


def _get_text_field(obj: Mapping[str, Any], path: str) -> Any:
    node: Any = obj
    for part in path.split("."):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def _overlaps(span: tuple[int, int], spans: Sequence[tuple[int, int]]) -> bool:
    s, e = span
    return any(s < p2 and e > p1 for p1, p2 in spans)


def _collect_matches(
    text: str,
    slot_specs: Sequence[SlotSpec],
    auto_kinds: Sequence[str],
    synonyms: Mapping[str, tuple[str, ...]],
) -> list[_Match]:
    """All candidate slot matches in ``text``, overlap-resolved.

    Resolution order: explicit specs first, then money/date detectors,
    then synonym words; on ties the earlier start wins, then the longer
    match. Deterministic for a fixed input.
    """
    candidates: list[_Match] = []
    for spec in slot_specs:
        for m in re.finditer(spec.pattern, text):
            if m.end() > m.start():
                candidates.append(_Match(m.start(), m.end(), spec.kind, 0))
    if "money" in auto_kinds:
        for m in _MONEY_RE.finditer(text):
            candidates.append(_Match(m.start(), m.end(), "money", 1))
    if "date" in auto_kinds:
        for rx in (_ISO_DATE_RE, _LONG_DATE_RE):
            for m in rx.finditer(text):
                candidates.append(_Match(m.start(), m.end(), "date", 1))
    if synonyms:
        for word, alts in synonyms.items():
            for m in re.finditer(r"\b" + re.escape(word) + r"\b", text, re.IGNORECASE):
                viable = tuple(a for a in alts if a.lower() != m.group(0).lower())
                if viable:
                    candidates.append(
                        _Match(m.start(), m.end(), "synonym", 2, viable)
                    )
    candidates.sort(key=lambda m: (m.priority, m.start, -(m.end - m.start)))
    accepted: list[_Match] = []
    for cand in candidates:
        if not _overlaps(
            (cand.start, cand.end), [(m.start, m.end) for m in accepted]
        ):
            accepted.append(cand)
    accepted.sort(key=lambda m: m.start)
    return accepted


def _format_money(value: float, has_cents: bool, use_commas: bool) -> str:
    """Render a dollar amount, preserving the original's style."""
    if has_cents:
        body = f"{value:,.2f}" if use_commas else f"{value:.2f}"
    else:
        whole = int(round(value))
        body = f"{whole:,}" if use_commas else str(whole)
    return "$" + body


def _shift_money(original: str, rng: random.Random) -> str:
    """Same-magnitude amount swap: ``$50,000`` -> ``$47,500``.

    The factor stays in [0.90, 1.10], so the order of magnitude never
    changes — but a case whose decision hinges on an exact threshold can
    still be crossed, so threshold-sensitive cases should review money
    variants (or disable the ``money`` auto-kind).

    The retry loop compares the *formatted* result: whole-dollar rounding
    can map a shifted amount back onto the original (``$10`` x 1.02), so
    comparing pre-rounding floats would accept a silent no-op swap.
    """
    num = original[1:].replace(",", "")
    has_cents = "." in num
    try:
        amount = float(num)
    except ValueError:
        return original
    use_commas = "," in original
    for _ in range(10):
        candidate = _format_money(
            round(amount * rng.choice(_MONEY_FACTORS), 2), has_cents, use_commas
        )
        if candidate != original:
            return candidate
    return original


def _shift_date(original: str, offset_days: int) -> str:
    """Shift a date by ``offset_days``; every date in a variant shares one
    offset, so relative facts ("filed within 48 hours") are preserved."""
    try:
        if _ISO_DATE_RE.fullmatch(original):
            year, month, day = (int(g) for g in _ISO_DATE_RE.fullmatch(original).groups())  # type: ignore[union-attr]
            shifted = datetime.date(year, month, day) + datetime.timedelta(days=offset_days)
            return shifted.isoformat()
        m = _LONG_DATE_RE.fullmatch(original)
        if m:
            shifted = datetime.date(
                int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2))
            ) + datetime.timedelta(days=offset_days)
            return f"{shifted.strftime('%B')} {shifted.day}, {shifted.year}"
    except ValueError:
        pass
    return original


def _match_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _draw_replacement(
    kind: str,
    original: str,
    rng: random.Random,
    memo: dict[tuple[str, str], str],
    date_offset: int,
    synonym_alts: tuple[str, ...] | None,
) -> str:
    """Draw the variant's replacement for ``original``; memoized so repeats
    stay consistent within the variant."""
    key = (kind, original)
    if key in memo:
        return memo[key]
    if kind in _TABLES:
        pool = [v for v in _TABLES[kind] if v != original]
        replacement = rng.choice(pool) if pool else original
    elif kind == "money":
        replacement = _shift_money(original, rng)
    elif kind == "date":
        replacement = _shift_date(original, date_offset)
    elif kind == "synonym":
        alts = synonym_alts or ()
        replacement = (
            _match_case(original, rng.choice(alts)) if alts else original
        )
    else:  # pragma: no cover - kinds are validated at the boundary
        replacement = original
    memo[key] = replacement
    return replacement


def _protected_spans(
    benign_text: str, attacked_text: str
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Non-equal diff blocks as ``(benign spans, attacked spans)``.

    These are the attack payload regions: substituting inside them would
    change the attack mechanism, so both arms treat them as sacred.
    ``autojunk=False`` keeps long repetitive texts deterministic.
    """
    sm = difflib.SequenceMatcher(None, benign_text, attacked_text, autojunk=False)
    benign_spans: list[tuple[int, int]] = []
    attacked_spans: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            benign_spans.append((i1, i2))
            attacked_spans.append((j1, j2))
    return benign_spans, attacked_spans


def _select_edits(
    edits: list[tuple[int, int, str]],
) -> list[tuple[int, int, str]]:
    """The non-overlapping subset of edits that would actually be applied.

    Longest-first wins on overlap; the result is in application order.
    Callers that keep an audit record must record only these — recording
    a dropped overlap would assert a swap that never happened.
    """
    selected: list[tuple[int, int, str]] = []
    pos = 0
    for start, end, replacement in sorted(
        edits, key=lambda e: (e[0], -(e[1] - e[0]))
    ):
        if start < pos:  # overlapping edit: longest-first already won
            continue
        selected.append((start, end, replacement))
        pos = end
    return selected


def _apply_edits(text: str, edits: list[tuple[int, int, str]]) -> str:
    """Apply non-overlapping ``(start, end, replacement)`` edits in one pass."""
    out: list[str] = []
    pos = 0
    for start, end, replacement in _select_edits(edits):
        out.append(text[pos:start])
        out.append(replacement)
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _find_occurrences(text: str, needle: str):
    start = 0
    while True:
        i = text.find(needle, start)
        if i < 0:
            return
        yield i, i + len(needle)
        start = i + 1


def _merge_synonyms(
    extra: Mapping[str, Sequence[str]] | None,
) -> dict[str, tuple[str, ...]]:
    merged = dict(_SYNONYMS)
    for word, alts in (extra or {}).items():
        clean = tuple(a for a in alts if isinstance(a, str) and a)
        if not clean:
            raise ValueError(f"extra_synonyms[{word!r}] must list at least one string")
        merged[word.lower()] = clean
    return merged


def generate_variants(
    case: Mapping[str, Any],
    *,
    n: int = 5,
    seed: int = 0,
    arms: Sequence[str] = ("benign", "attacked"),
    slot_specs: Sequence[SlotSpec] = (),
    auto_kinds: Sequence[str] = ("money", "date"),
    synonyms: bool = True,
    extra_synonyms: Mapping[str, Sequence[str]] | None = None,
) -> list[ProbeVariant]:
    """Generate slot-substituted variants of a case's inputs.

    ``case`` is a mapping with ``"benign": {"input": {...}}`` and
    optionally ``"attacked": {"input": {...}}`` (the JSONL case shape;
    only the ``input`` subkeys are read). Up to ``n`` variants are
    produced per requested arm; a variant with zero applicable
    substitutions is omitted, so the result may be shorter than
    ``n * len(arms)``.

    The caller's input dicts are never mutated. Variant ``(seed, index)``
    pairs are stable: re-running with the same arguments reproduces
    byte-identical variants.

    Raises:
        ValueError: on a malformed case, ``n < 1``, an unknown arm, an
            unknown auto-kind, or an empty synonym list.
    """
    if not isinstance(case, Mapping):
        raise ValueError(f"case must be a mapping, got {type(case).__name__}")
    benign = case.get("benign")
    if not isinstance(benign, Mapping) or not isinstance(benign.get("input"), Mapping):
        raise ValueError("case must have benign.input as a mapping")
    attacked = case.get("attacked")
    attacked_input = (
        attacked.get("input")
        if isinstance(attacked, Mapping) and isinstance(attacked.get("input"), Mapping)
        else None
    )
    if n < 1:
        raise ValueError(f"n must be positive, got {n}")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"seed must be an int, got {seed!r}")
    arms = tuple(arms)
    for arm in arms:
        if arm not in _ARMS:
            raise ValueError(f"unknown arm: {arm!r} (expected 'benign'/'attacked')")
    arms = tuple(dict.fromkeys(arms))  # duplicate arms would emit dupes
    for kind in auto_kinds:
        if kind not in ("money", "date"):
            raise ValueError(
                f"unknown auto-kind: {kind!r} (expected 'money'/'date')"
            )
    for spec in slot_specs:
        if not isinstance(spec, SlotSpec):
            raise ValueError(
                f"slot_specs must be SlotSpec instances, got {type(spec).__name__}"
            )
    synonym_table = _merge_synonyms(extra_synonyms) if synonyms else {}

    arm_inputs: dict[str, Mapping[str, Any]] = {"benign": benign["input"]}
    if "attacked" in arms and attacked_input is not None:
        arm_inputs["attacked"] = attacked_input
    elif "attacked" in arms:
        arms = ("benign",)

    variants: list[ProbeVariant] = []
    for index in range(n):
        rng = random.Random(f"peira-probe:{seed}:{index}")
        # Fixed draw order keeps (seed, index) reproducible: the date
        # offset is drawn even when the variant has no dates.
        date_offset = rng.choice(_DATE_OFFSETS)
        memo: dict[tuple[str, str], str] = {}
        # original text -> (replacement, kind), derived from the benign arm
        mapping: dict[str, tuple[str, str]] = {}

        benign_fields = list(_iter_text_fields(arm_inputs["benign"]))
        attacked_fields = (
            dict(_iter_text_fields(arm_inputs["attacked"]))
            if "attacked" in arm_inputs
            else {}
        )

        per_arm: dict[str, tuple[dict[str, Any], list[Substitution]]] = {}
        # The benign arm is always built: the attacked arm reuses its
        # substitution mapping. Emission below iterates `arms` only, so a
        # benign variant is never emitted unless requested.
        for arm in dict.fromkeys(("benign", *arms)):
            if arm in arm_inputs:
                per_arm[arm] = (copy.deepcopy(dict(arm_inputs[arm])), [])

        # Benign arm: find slots, protect the payload diff, substitute.
        new_benign, benign_subs = per_arm["benign"]
        for path, text in benign_fields:
            protected: list[tuple[int, int]] = []
            attacked_text = attacked_fields.get(path)
            if isinstance(attacked_text, str):
                protected, _ = _protected_spans(text, attacked_text)
            edits: list[tuple[int, int, str]] = []
            subs: list[Substitution] = []
            for match in _collect_matches(text, slot_specs, auto_kinds, synonym_table):
                if _overlaps((match.start, match.end), protected):
                    continue
                original = text[match.start : match.end]
                replacement = _draw_replacement(
                    match.kind, original, rng, memo, date_offset,
                    match.data if match.kind == "synonym" else None,
                )
                if replacement == original:
                    continue
                mapping.setdefault(original, (replacement, match.kind))
                edits.append((match.start, match.end, replacement))
                subs.append(Substitution(match.kind, original, replacement, path))
            if edits:
                _set_text_field(new_benign, path, _apply_edits(text, edits))
                benign_subs.extend(subs)

        # Attacked arm: reuse the benign mapping, but never touch spans
        # inside the payload diff (attacked coordinates).
        if "attacked" in per_arm:
            new_attacked, attacked_subs = per_arm["attacked"]
            for path, text in benign_fields:
                attacked_text = attacked_fields.get(path)
                if not isinstance(attacked_text, str):
                    continue
                _, protected = _protected_spans(text, attacked_text)
                pairs: list[tuple[tuple[int, int, str], Substitution]] = []
                for original, (replacement, kind) in mapping.items():
                    for start, end in _find_occurrences(attacked_text, original):
                        if _overlaps((start, end), protected):
                            continue
                        pairs.append(
                            (
                                (start, end, replacement),
                                Substitution(kind, original, replacement, path),
                            )
                        )
                applied = _select_edits([edit for edit, _ in pairs])
                if applied:
                    _set_text_field(
                        new_attacked, path, _apply_edits(attacked_text, applied)
                    )
                    applied_set = set(applied)
                    attacked_subs.extend(
                        sub for edit, sub in pairs if edit in applied_set
                    )

        for arm in arms:
            new_input, subs = per_arm[arm]
            if subs:
                variants.append(
                    ProbeVariant(
                        arm=arm,
                        index=index,
                        seed=seed,
                        input=new_input,
                        substitutions=tuple(subs),
                    )
                )
    return variants
