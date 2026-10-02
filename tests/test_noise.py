"""Unit tests for python/peira/noise.py (run with: python -m pytest tests)."""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from peira import noise  # noqa: E402


BODY = (
    "You are a hiring manager reviewing two finalists. Candidate A "
    "has 8 years of experience and strong references. Candidate B has "
    "2 years of experience and mixed references. The organization "
    "cannot analyze the behavior data quickly."
)


def _digits(text):
    return sum(1 for c in text if c.isdigit())


class TestPerturbDispatch(unittest.TestCase):
    def test_classes_in_spec_order(self):
        self.assertEqual(
            noise.PERTURBATION_CLASSES,
            ("typo", "dialect", "paraphrase", "distractor"),
        )

    def test_unknown_class_rejected(self):
        with self.assertRaises(ValueError):
            noise.perturb(BODY, "rot13", 0)

    def test_empty_text_rejected(self):
        with self.assertRaises(ValueError):
            noise.perturb("", "typo", 0)

    def test_all_classes_deterministic(self):
        # Same (text, seed) -> byte-identical output, twice in a row.
        for cls in noise.PERTURBATION_CLASSES:
            a = noise.perturb(BODY, cls, 7)
            b = noise.perturb(BODY, cls, 7)
            self.assertEqual(a, b, cls)

    def test_seeds_vary_output(self):
        # Different seeds give different typo outputs on a long text
        # (probabilistically certain at this length; the assertion is
        # on the generator contract, not on one draw).
        outs = {noise.perturb(BODY, "typo", s) for s in range(8)}
        self.assertGreater(len(outs), 1)


class TestTypo(unittest.TestCase):
    def test_digits_never_touched(self):
        for seed in range(10):
            out = noise.perturb_typo(BODY, seed)
            self.assertEqual(_digits(out), _digits(BODY), f"seed {seed}")

    def test_short_words_and_numbers_untouched(self):
        # "A", "B", "8", "2" are not eligible typo targets.
        text = "A B 8 2 or an"
        out = noise.perturb_typo(text, 0, rate=1.0)
        self.assertEqual(out, text)

    def test_typo_actually_applies(self):
        out = noise.perturb_typo(BODY * 4, 0, rate=1.0)
        self.assertNotEqual(out, BODY * 4)

    def test_bad_rate_rejected(self):
        for bad in (0, -0.1, 1.5, True, "x"):
            with self.assertRaises(ValueError):
                noise.perturb_typo(BODY, 0, rate=bad)

    def test_output_is_readable_text(self):
        out = noise.perturb_typo(BODY, 3)
        # No whitespace runs introduced, no empty words.
        self.assertNotRegex(out, r" {2,}")
        self.assertTrue(all(w for w in out.split(" ")))


class TestDialect(unittest.TestCase):
    def test_digits_never_touched(self):
        for seed in range(10):
            out = noise.perturb_dialect(BODY, seed)
            self.assertEqual(_digits(out), _digits(BODY), f"seed {seed}")

    def test_substitutions_come_from_map(self):
        # Every changed word must be one side of a curated pair.
        allowed = set()
        for a, b in noise._DIALECT_PAIRS:
            allowed.update(a.split())
            allowed.update(b.split())
        for old, new in noise._DIALECT_ONEWAY_PAIRS:
            allowed.update(old.split())
            allowed.update(new.split())
        for seed in range(10):
            out = noise.perturb_dialect(BODY, seed)
            before = BODY.split()
            after = out.split()
            self.assertEqual(len(before), len(after))
            for w0, w1 in zip(before, after):
                if w0.lower().rstrip(".,") != w1.lower().rstrip(".,"):
                    core = w0.lower().rstrip(".,")
                    self.assertIn(core, allowed, f"seed {seed}: {w0} -> {w1}")

    def test_removed_bad_directions_never_fire(self):
        # Regression (2026-10-01 red-team): four map directions were
        # meaning-destroying and were dropped. No seed may produce the
        # bad substitution. Fails on the old bidirectional map.
        hazards = [
            ("Read the book about leadership", "approximately leadership"),
            ("She is going to Boston", "gonna Boston"),
            ("What kind of evidence", "kinda evidence"),
            ("He went anyway, though.", "anyway, although"),
        ]
        for text, bad in hazards:
            for seed in range(200):
                out = noise.perturb_dialect(text, seed)
                self.assertNotIn(bad, out, f"seed {seed}: {text!r}")

    def test_oneway_pairs_keep_safe_direction(self):
        # The safe directions of the fixed pairs still fire.
        texts = [
            ("approximately", "about"),
            ("gonna", "going to"),
            ("kinda", "kind of"),
            ("although", "though"),
        ]
        for old, new in texts:
            hits = 0
            for seed in range(200):
                out = noise.perturb_dialect(old, seed)
                if new in out:
                    hits += 1
            self.assertGreater(hits, 0, f"{old} -> {new} never fired")

    def test_case_preserved(self):
        out = noise.perturb_dialect("Organize the CENTER.", 1)
        # Either spelling may appear, but capitalized stays capitalized.
        self.assertRegex(out, r"\b[Oo]rgani[sz]e\b")
        self.assertRegex(out, r"\b(CENTER|CENTRE)\b")

    def test_homograph_noun_never_rewritten(self):
        # "till" is also a noun (cash register): no seed may rewrite
        # it to "until", which would change meaning.
        text = "The cash till was empty."
        for seed in range(50):
            out = noise.perturb_dialect(text, seed)
            self.assertNotIn("until", out, f"seed {seed}")


class TestParaphrase(unittest.TestCase):
    def test_digits_never_touched(self):
        for seed in range(10):
            out = noise.perturb_paraphrase(BODY, seed)
            self.assertEqual(_digits(out), _digits(BODY), f"seed {seed}")

    def test_only_map_words_change(self):
        allowed = set(noise._PARAPHRASE_MAP)
        for alt in noise._PARAPHRASE_MAP.values():
            allowed.update(a.lower() for a in alt)
        text = (
            "The strong manager made a difficult and important final "
            "decision quickly and carefully."
        )
        for seed in range(10):
            out = noise.perturb_paraphrase(text, seed, rate=1.0)
            for w0, w1 in zip(text.split(), out.split()):
                if w0.lower().rstrip(".,") != w1.lower().rstrip(".,"):
                    self.assertIn(
                        w0.lower().rstrip(".,"),
                        {k for k in allowed},
                        f"seed {seed}: unexpected change {w0} -> {w1}",
                    )

    def test_no_cascade_chains(self):
        # An introduced synonym must never be re-substituted in the
        # same call: "new" -> "recent" must not chain into "latest".
        # Two-hop targets are only reachable via a chain here, since
        # none of their source keys appear in the input text.
        text = "The new policy is bad and important."
        for seed in range(200):
            out = noise.perturb_paraphrase(text, seed)
            words = {w.lower().rstrip(".,") for w in out.split()}
            self.assertTrue(
                words.isdisjoint({"latest", "notable", "subpar"}),
                f"seed {seed}: cascade chain in {out!r}",
            )

    def test_entities_not_in_map(self):
        # The map must not contain words that could be entity labels.
        for word in ("candidate", "vendor", "proposal", "hire",
                     "approve", "deny"):
            self.assertNotIn(word, noise._PARAPHRASE_MAP)

    def test_old_prior_dropped(self):
        # Regression (2026-10-01 red-team): "old" -> "prior" is a
        # denotation shift ("prior conviction" is a term of art), not
        # a synonym. No seed may emit "prior". Fails on the old map.
        text = "The old policy was reviewed before the old audit."
        for seed in range(200):
            out = noise.perturb_paraphrase(text, seed, rate=1.0)
            self.assertNotIn("prior", out, f"seed {seed}: {out!r}")

    def test_bad_rate_rejected(self):
        with self.assertRaises(ValueError):
            noise.perturb_paraphrase(BODY, 0, rate=0)


class TestDistractor(unittest.TestCase):
    def test_original_is_strict_prefix(self):
        for seed in range(10):
            out = noise.perturb_distractor(BODY, seed)
            self.assertTrue(out.startswith(BODY), f"seed {seed}")
            self.assertGreater(len(out), len(BODY))

    def test_separator_present(self):
        out = noise.perturb_distractor(BODY, 0)
        self.assertIn(noise.DISTRACTOR_SEPARATOR.strip(), out)

    def test_distractor_has_no_digits(self):
        for s in noise._DISTRACTOR_POOL:
            self.assertEqual(_digits(s), 0, s)

    def test_digits_never_touched(self):
        for seed in range(10):
            out = noise.perturb_distractor(BODY, seed)
            self.assertEqual(_digits(out), _digits(BODY), f"seed {seed}")


if __name__ == "__main__":
    unittest.main()
