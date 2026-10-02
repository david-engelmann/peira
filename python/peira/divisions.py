"""Canonical leaderboard division vocabulary.

Single source of truth for the two leaderboard divisions
(docs/Admission-Rules.md). ``python/peira/cli.py`` (``--division``
choices), ``site/scripts/ingest.py`` (division validation), and
``site/scripts/render_og.py`` (division labels) all import from here;
the site JS reads the vocabulary from the ingested ``results.json``.

Add a division here and the Python consumers pick it up; the static
``DivisionToggle.astro`` buttons still need a manual key sync (locked by
``TestDivisionVocabularySync.test_division_toggle_keys_match_canonical``).
"""

DIVISIONS: tuple[tuple[str, str], ...] = (
    ("guardrail", "Guardrail division"),
    ("llm-baseline", "LLM baseline division"),
)

DIVISION_KEYS: frozenset[str] = frozenset(key for key, _ in DIVISIONS)

DIVISION_LABELS: dict[str, str] = dict(DIVISIONS)


def division_label(key: str) -> str:
    """Human label for a division key; unknown keys pass through."""
    return DIVISION_LABELS.get(key, key)
