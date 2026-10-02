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
        # Regression (2026-10-01 and 2026-10-02 red-team): six map
        # directions were meaning-destroying and were dropped. No seed
        # may produce the bad substitution. Fails on the old maps.
        hazards = [
            ("Read the book about leadership", "approximately leadership"),
            ("She is going to Boston", "gonna Boston"),
            ("What kind of evidence", "kinda evidence"),
            ("He went anyway, though.", "anyway, although"),
            ("The use of force was reviewed.", "utilize of force"),
            ("Drug use declined last year.", "Drug utilize"),
            ("She also signed the petition.", "furthermore signed"),
            ("I also like cake.", "I furthermore"),
        ]
        for text, bad in hazards:
            for seed in range(200):
                out = noise.perturb_dialect(text, seed)
                self.assertNotIn(bad, out, f"seed {seed}: {text!r}")

    def test_oneway_pairs_keep_safe_direction(self):
        # The safe directions of the fixed pairs still fire. Each leg
        # uses a probe where the old word is a standalone token and
        # asserts the standalone new word appears while the old word
        # is gone. (The old ("although", "though") leg asserted
        # "though" in out on the probe "although", which is trivially
        # true since "though" is a substring of "although".)
        legs = [
            ("approximately ten people came", r"approximately",
             r"(?<![\w-])about(?![\w-])"),
            ("she is gonna leave", r"gonna", r"going to"),
            ("what kinda evidence is this", r"kinda", r"kind of"),
            ("Although it rained, we stayed.",
             r"(?<![\w-])although(?![\w-])",
             r"(?<![\w-])though(?![\w-])"),
            ("Please utilize the form.", r"utilize",
             r"(?<![\w-])use(?![\w-])"),
            ("Furthermore, the data agree.", r"furthermore",
             r"(?<![\w-])also(?![\w-])"),
        ]
        for probe, old_pat, new_pat in legs:
            hits = 0
            for seed in range(200):
                out = noise.perturb_dialect(probe, seed)
                if (re.search(old_pat, out, re.IGNORECASE) is None
                        and re.search(new_pat, out, re.IGNORECASE)):
                    hits += 1
            self.assertGreater(
                hits, 0, f"{probe!r}: safe direction never fired")

    def test_no_cross_pair_cascade(self):
        # Safety invariant (see the map comment): no pair's output
        # whole-word-matches a DIFFERENT pair's input, so sequential
        # per-pair application can never cascade across pairs. Fails
        # if a future map edit introduces a cross-pair chain.
        pairs = list(noise._DIALECT_PAIRS) + \
            list(noise._DIALECT_ONEWAY_PAIRS)
        for i, (a, b) in enumerate(pairs):
            for j, (c, d) in enumerate(pairs):
                if i == j:
                    continue
                for out in (a, b):
                    out_words = set(out.lower().split())
                    for inp in (c, d):
                        self.assertNotEqual(
                            out.lower(), inp.lower(),
                            f"pair {i} output {out!r} matches "
                            f"pair {j} input {inp!r}")
                        if " " not in inp:
                            self.assertNotIn(
                                inp.lower(), out_words,
                                f"pair {i} output {out!r} contains "
                                f"pair {j} input word {inp!r}")

    def test_proper_nouns_survive(self):
        # Regression (2026-10-02 re-sweep): proper nouns must survive
        # dialect perturbation. Fails on the pre-guard map.
        corpus = [
            ("The Rockefeller Center tour.", "Rockefeller Center"),
            ("The Center for Disease Control met.", "Center for"),
            ("Gray resigned yesterday.", "Gray resigned"),
            ("Earl Grey tea is served.", "Earl Grey"),
            ("Zane Grey wrote novels.", "Zane Grey"),
            ("Organizational Behavior is a field.",
             "Organizational Behavior"),
            ("The Defense Department announced.", "Defense Department"),
        ]
        for text, phrase in corpus:
            for seed in range(50):
                out = noise.perturb_dialect(text, seed)
                self.assertIn(
                    phrase, out, f"seed {seed}: {text!r} -> {out!r}")

    def test_hyphen_compounds_not_split(self):
        # Regression (2026-10-02 re-sweep): hyphen-aware boundaries
        # stop "wanna-be" becoming "want to-be". Fails on the old
        # boundaries.
        for seed in range(100):
            out = noise.perturb_dialect("A wanna-be actor left.", seed)
            self.assertNotIn("want to-be", out,
                             f"seed {seed}: {out!r}")

    def test_guards_keep_common_words_substituting(self):
        # The proper-noun and lowercase-only guards must not kill
        # ordinary lowercase substitutions.
        for text, frag in [
            ("the gray area is unclear.", "grey"),
            ("Please organize the files.", "rganise"),
            ("the center of town", "centre"),
        ]:
            hits = sum(1 for s in range(200)
                       if frag in noise.perturb_dialect(text, s))
            self.assertGreater(
                hits, 0, f"{text!r}: {frag!r} never fired")

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

    def test_dropped_entries_absent(self):
        # The 2026-10-02 re-sweep dropped eight entries, each
        # demonstrated hazardous (see the map comments). They must
        # stay out of the map. Fails on the old map.
        for dropped in ("old", "high", "slow", "very", "final",
                        "experienced", "brief", "clear"):
            self.assertNotIn(dropped, noise._PARAPHRASE_MAP)

    def test_map_structural_invariants(self):
        # Class-level guard: keys and alternatives are lowercase
        # single words, and the audit-dropped entries stay dropped.
        for key, alts in noise._PARAPHRASE_MAP.items():
            self.assertRegex(key, r"^[a-z]+$", f"key {key!r}")
            for alt in alts:
                self.assertRegex(alt, r"^[a-z]+$", f"alt {alt!r}")
        for dropped in ("old", "high", "slow", "very", "final",
                        "experienced", "brief", "clear"):
            self.assertNotIn(dropped, noise._PARAPHRASE_MAP)

    def _never(self, text, bad, seeds=200):
        # Helper: at rate=1.0 every key is chosen, so a guard hole
        # shows up on every seed, not just some.
        for seed in range(seeds):
            out = noise.perturb_paraphrase(text, seed, rate=1.0)
            self.assertNotIn(bad, out,
                             f"seed {seed}: {text!r} -> {out!r}")

    def test_new_york_never_becomes_recent_york(self):
        # Regression (2026-10-02): "New York" -> "Recent York" is
        # proper-noun destruction. Fails on the old map.
        self._never("She moved to New York in June.", "Recent York")
        self._never("The New Deal reshaped policy.", "Recent Deal")
        for seed in range(50):
            out = noise.perturb_paraphrase(
                "She moved to New York in June.", seed, rate=1.0)
            self.assertIn("New York", out, f"seed {seed}: {out!r}")
        # The legitimate use still fires.
        out = noise.perturb_paraphrase(
            "A new policy was announced.", 0, rate=1.0)
        self.assertEqual(out, "A recent policy was announced.")

    def test_main_street_preserved(self):
        # Regression (2026-10-02): "Main Street" -> "Primary Street".
        self._never("The office is on Main Street.", "Primary Street")
        self._never("The Main Line train left.", "Primary Line")
        out = noise.perturb_paraphrase(
            "the main reason was cost.", 0, rate=1.0)
        self.assertEqual(out, "the primary reason was cost.")

    def test_high_school_dropped(self):
        # Regression (2026-10-02): "high school" -> "elevated school".
        # The entry was dropped, not guarded.
        self._never("He attended high school.", "elevated")

    def test_good_morning_preserved(self):
        # Regression (2026-10-02): "Good morning" -> "Solid morning".
        self._never("Good morning, team.", "Solid morning")
        self._never("They acted in good faith.", "solid faith")
        self._never("Good cop, bad cop.", "Solid cop")
        for seed in range(50):
            out = noise.perturb_paraphrase(
                "Good morning, team.", seed, rate=1.0)
            self.assertIn("Good morning", out, f"seed {seed}: {out!r}")
        out = noise.perturb_paraphrase(
            "A good result was posted.", 0, rate=1.0)
        self.assertEqual(out, "A solid result was posted.")

    def test_poor_family_preserved(self):
        # Regression (2026-10-02): "The poor family" -> "The subpar
        # family" shifts impoverished to low-quality.
        self._never("The poor family received aid.", "subpar family")
        self._never("The poor thing cried.", "subpar thing")
        out = noise.perturb_paraphrase(
            "Poor performance was noted.", 0, rate=1.0)
        self.assertEqual(out, "Subpar performance was noted.")

    def test_steady_hand_preserved(self):
        # Regression (2026-10-02): "a steady hand" -> "a stable hand"
        # ("stable hand" is a distinct noun phrase).
        self._never("She has a steady hand.", "stable hand")
        self._never("A steady gaze met his.", "stable gaze")
        out = noise.perturb_paraphrase(
            "Steady progress continued.", 0, rate=1.0)
        self.assertEqual(out, "Stable progress continued.")

    def test_brief_dropped(self):
        # Regression (2026-10-02): "filed a brief" -> "filed a
        # short" (legal-noun sense). The entry was dropped.
        for seed in range(200):
            out = noise.perturb_paraphrase(
                "She filed a brief.", seed, rate=1.0)
            self.assertEqual(out, "She filed a brief.",
                             f"seed {seed}: {out!r}")

    def test_break_a_fast_preserved(self):
        # Regression (2026-10-02): "break a fast" -> "break a rapid"
        # (noun sense) and "run fast" -> "run quick" (adverb sense).
        self._never("They break a fast at dawn.", "a rapid")
        self._never("They break a fast at dawn.", "a quick")
        self._never("Run fast to win.", "Run quick")
        self._never("How fast is it?", "How quick")
        self._never("The fast of Ramadan ended.", "quick of")
        out = noise.perturb_paraphrase("A fast car won.", 0, rate=1.0)
        self.assertEqual(out, "A quick car won.")

    def test_small_man_never_modest(self):
        # Regression (2026-10-02): "the small man" -> "the modest
        # man" shifts size to a humility trait. "modest" was dropped
        # from the alternatives.
        self._never("The small man left.", "modest man")
        out = noise.perturb_paraphrase(
            "A small room was booked.", 0, rate=1.0)
        self.assertEqual(out, "A little room was booked.")

    def test_very_good_never_highly(self):
        # Regression (2026-10-02): "very good" -> "highly good" is
        # ungrammatical ("highly" is collocation-bound). The entry
        # was dropped.
        self._never("The result was very good.", "highly")

    def test_in_recent_years_preserved(self):
        # Regression (2026-10-02): "In recent years" -> "In latest
        # years" and "a recent study" -> "a latest study".
        self._never("In recent years, costs rose.", "latest years")
        self._never("A recent study found risk.", "latest study")
        self._never("The most recent data show.", "most latest")
        out = noise.perturb_paraphrase(
            "The recent changes helped.", 0, rate=1.0)
        self.assertEqual(out, "The latest changes helped.")

    def test_low_blow_preserved(self):
        # Regression (2026-10-02): "a low blow" -> "a reduced blow"
        # (idiom), "low key" -> "reduced key", weather-noun "low".
        self._never("That was a low blow.", "reduced blow")
        self._never("Keep it low key.", "reduced key")
        self._never("A low tide exposed rocks.", "reduced tide")
        self._never("Low-hanging fruit first.", "Reduced-hanging")
        out = noise.perturb_paraphrase(
            "Low morale spread.", 0, rate=1.0)
        self.assertEqual(out, "Reduced morale spread.")

    def test_weak_never_frail(self):
        # Re-sweep trim: "frail" adds a physical-frailty connotation
        # ("the frail team"). Only "feeble" is kept.
        self._never("The weak team lost.", "frail")
        out = noise.perturb_paraphrase(
            "The weak team lost.", 0, rate=1.0)
        self.assertEqual(out, "The feeble team lost.")

    def test_large_language_model_preserved(self):
        # Re-sweep guard: "large language model" and "large cap" are
        # terms of art.
        self._never("A large language model was used.",
                    "big language model")
        self._never("A large language model was used.",
                    "sizable language model")
        self._never("Large cap stocks fell.", "Big cap")
        out = noise.perturb_paraphrase(
            "A large crowd gathered.", 0, rate=1.0)
        self.assertNotEqual(out, "A large crowd gathered.")

    def test_significant_other_preserved(self):
        # Re-sweep guard: "significant other" and the statistical
        # term of art.
        self._never("His significant other called.", "notable other")
        self._never("A statistically significant effect.",
                    "statistically notable")
        self._never("Significant figures matter.", "Notable figures")
        out = noise.perturb_paraphrase(
            "A significant result emerged.", 0, rate=1.0)
        self.assertEqual(out, "A notable result emerged.")

    def test_an_important_no_article_clash(self):
        # Re-sweep find: "An important" -> "An significant" is an
        # article clash (both alternatives are consonant-initial).
        self._never("An important decision looms.", "An significant")
        self._never("An important decision looms.", "An key")
        out = noise.perturb_paraphrase(
            "The important factor won.", 0, rate=1.0)
        self.assertNotEqual(out, "The important factor won.")

    def test_proper_nouns_survive_paraphrase(self):
        # Class-level guard: proper-noun runs survive paraphrase.
        corpus = [
            ("She moved to New York in June.", "New York"),
            ("The office is on Main Street.", "Main Street"),
            ("The New Deal reshaped policy.", "New Deal"),
            ("The Fast Company list grew.", "Fast Company"),
        ]
        for text, phrase in corpus:
            for seed in range(50):
                out = noise.perturb_paraphrase(
                    text, seed, rate=1.0)
                self.assertIn(
                    phrase, out, f"seed {seed}: {text!r} -> {out!r}")

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
