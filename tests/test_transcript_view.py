"""R-18: static HTML transcript viewer tests.

The viewer is stdlib-only and must HTML-escape every dynamic value so
hostile transcript content cannot break out of the page.
"""

import json
import tempfile
import unittest
from pathlib import Path

from peira.transcript_view import load_entries, render, write_html


def _entry(**kw):
    base = {
        "dispatch_index": 0,
        "case_id": "c1",
        "variant": "benign",
        "call_id": "x",
        "primitive": "choice",
        "request": {"input": {}, "primitive": "choice"},
        "response": {"kind": "output",
                     "output": {"decision": "approve", "confidence": 0.9}},
        "raw": None,
        "provider": {"adapter_name": "a", "adapter_version": "v",
                     "model": ""},
        "seed": 0,
        "latency_ms": 1.0,
        "attempt_latencies_ms": [],
        "latency_ms_total": 1.0,
        "timed_out": False,
        "token_limit_exceeded": False,
        "attempts": 1,
        "cached": False,
        "dispatch_limit": 1,
        "max_concurrency": 8,
    }
    base.update(kw)
    return base


class TestTranscriptView(unittest.TestCase):
    def _render(self, entries, bad_lines=()):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.jsonl"
            with open(p, "w", encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e) + "\n")
                for line in bad_lines:
                    f.write(line + "\n")
            return render(p)

    def test_summary_counts(self):
        html = self._render([
            _entry(dispatch_index=0),
            _entry(dispatch_index=1, timed_out=True),
            _entry(dispatch_index=2, token_limit_exceeded=True,
                   response={"kind": "error", "error": "boom",
                             "status_code": None, "retry_after": None}),
        ])
        for fragment in ("entries: 3", "outputs: 2", "errors: 1",
                         "timeouts: 1", "token-limit violations: 1"):
            self.assertIn(fragment, html)

    def test_hostile_content_is_escaped(self):
        evil = '</script><script>alert("x")</script><img src=x onerror=y>'
        html = self._render([
            _entry(case_id=evil,
                   response={"kind": "output",
                             "output": {"decision": evil}}),
        ])
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)

    def test_bad_lines_are_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.jsonl"
            p.write_text(json.dumps(_entry()) + "\nnot json\n",
                         encoding="utf-8")
            entries, bad = load_entries(p)
            self.assertEqual(len(entries), 1)
            self.assertEqual(bad, 1)
            html = render(p)
        self.assertIn("unparseable lines skipped: 1", html)

    def test_self_contained(self):
        html = self._render([_entry()])
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("<script", html)
        self.assertIn("<style>", html)

    def test_write_html_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td) / "t.jsonl"
            o = Path(td) / "view.html"
            t.write_text(json.dumps(_entry()) + "\n", encoding="utf-8")
            write_html(t, o)
            self.assertTrue(o.exists())
            self.assertIn("<!DOCTYPE html>",
                          o.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
