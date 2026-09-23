"""Tests for scripts/check_doc_links.py (run with: python -m unittest discover tests).

Covers the reference-style link pass: [text][label] / [text][] links
must resolve to a defined [label]: target, and the target itself is
checked like an inline link target.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path


def _load_script():
    path = (Path(__file__).resolve().parents[1] / "scripts"
            / "check_doc_links.py")
    spec = importlib.util.spec_from_file_location("check_doc_links", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


check_doc_links = _load_script()


class TestReferenceLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "README.md").write_text("# Home\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _page(self, name, text):
        p = self.root / "docs" / name
        p.write_text(text, encoding="utf-8")
        return p

    def _other(self):
        (self.root / "docs" / "other.md").write_text(
            "# Other Page\n\n## Section\n", encoding="utf-8")

    def test_valid_reference_link(self):
        self._other()
        self._page("a.md", "See [the other page][other].\n\n[other]: other.md\n")
        self.assertEqual(check_doc_links.check(self.root), [])

    def test_collapsed_reference_link(self):
        self._other()
        self._page("a.md", "See [Other][].\n\n[other]: other.md\n")
        self.assertEqual(check_doc_links.check(self.root), [])

    def test_reference_link_with_anchor(self):
        self._other()
        self._page("a.md",
                   "See [the section][sec].\n\n[sec]: other.md#section\n")
        self.assertEqual(check_doc_links.check(self.root), [])

    def test_dead_reference_target(self):
        self._page("a.md", "See [the missing][gone].\n\n[gone]: nope.md\n")
        problems = check_doc_links.check(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("dead link to nope.md", problems[0])
        self.assertIn("a.md:1:", problems[0])

    def test_dead_reference_anchor(self):
        self._other()
        self._page("a.md", "See [the section][sec].\n\n[sec]: other.md#nope\n")
        problems = check_doc_links.check(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("dead anchor #nope", problems[0])

    def test_undefined_reference(self):
        self._other()
        self._page("a.md", "See [the other][undefined].\n")
        problems = check_doc_links.check(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("undefined reference [undefined]", problems[0])

    def test_reference_labels_are_case_insensitive(self):
        self._other()
        self._page("a.md", "See [the other][OTHER].\n\n[other]: other.md\n")
        self.assertEqual(check_doc_links.check(self.root), [])

    def test_external_reference_target_skipped(self):
        self._page("a.md",
                   "See [the site][web].\n\n[web]: https://example.com/x\n")
        self.assertEqual(check_doc_links.check(self.root), [])


if __name__ == "__main__":
    unittest.main()
