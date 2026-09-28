"""Prose-style regression tests: no em dashes in v2-foundation public prose.

Standing standard: public docs read like a human engineer wrote them, and
em dashes are the #1 AI-writing tell. These tests pin the prose added by
the v2 family foundation (CLI reference, Taxonomy v2 entries,
Troubleshooting additions, runs_registry docstrings) to em-dash-free
wording. Pre-existing prose elsewhere in these files is out of scope and
is not asserted on here.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EM_DASH = "\u2014"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _section(text: str, start_marker: str, end_markers: tuple[str, ...]) -> str:
    """Text from start_marker up to the earliest end marker after it."""
    start = text.index(start_marker)
    end = len(text)
    for marker in end_markers:
        idx = text.find(marker, start + len(start_marker))
        if idx != -1:
            end = min(end, idx)
    return text[start:end]


class TestNoEmDashes(unittest.TestCase):
    def test_cli_families_prose(self):
        text = _read("docs/CLI.md")
        row = re.search(r"\| `--families` \|[^\n]*\n", text)
        self.assertIsNotNone(row, "expected a --families row in docs/CLI.md")
        self.assertNotIn(EM_DASH, row.group(0))
        section = _section(text, "## peira family-summary", ("## peira dataset",))
        self.assertNotIn(EM_DASH, section)

    def test_taxonomy_v2_entries(self):
        text = _read("docs/Taxonomy.md")
        section = _section(text, "11. **", ("## Family boundary rulings",))
        self.assertNotIn(EM_DASH, section)
        # The reworded criteria_smuggling entry: the one v1 line this
        # feature rewrote, so its prose is in scope.
        entry = re.search(
            r"2\. \*\*criteria_smuggling\*\*:[^\n]*\n(?:    [^\n]*\n)*", text
        )
        self.assertIsNotNone(entry, "expected the reworded criteria_smuggling entry")
        self.assertNotIn(EM_DASH, entry.group(0))

    def test_troubleshooting_new_entries(self):
        text = _read("docs/Troubleshooting.md")
        for header in (
            "**`error: unknown famil(ies): x (known families: ...)`**",
            "**`peira dataset new: error: argument --family: invalid choice: 'x'`**",
        ):
            section = _section(text, header, ("\n**`", "\n## "))
            self.assertNotIn(EM_DASH, section, f"em dash in {header}")

    def test_runs_registry_docstrings(self):
        text = _read("python/peira/runs_registry.py")
        # verify_runs holds the docstring this feature added prose to. The
        # module docstring's older em dash predates the feature and is out
        # of scope, so the check starts at the function.
        start = text.index("def verify_runs(")
        self.assertNotIn(EM_DASH, text[start : start + 2000])


if __name__ == "__main__":
    unittest.main()
