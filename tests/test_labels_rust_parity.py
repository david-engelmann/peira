"""Backend-parity tests for ``peira.adapters._labels`` (rust-max SLICE-2).

Each test compares the dispatched public function (the compiled Rust
core when ``peira._core`` is importable, the ``_xxx_py`` reference
otherwise) against the pure-Python ``_xxx_py`` reference on identical
inputs. Exact equality: lists order-identical, strings identical.

When the Rust extension is absent the dispatched function *is* the
reference, so the tests hold trivially and still pin the reference
behavior. ``test_backend_under_test`` records which backend ran so the
gate report can confirm Rust-active mode actually exercised the core.

Error parity: the dispatched entry point validates before dispatch
(D-11), so both backends raise the same exception types and messages.
"""

import os
import random
import unittest

import peira.adapters._labels as labels_mod
from peira._rust import _impl as _rust
from peira.adapters._labels import (
    NON_ABSTAIN_PLACEHOLDER,
    _candidate_labels_py,
    _non_abstain_placeholder_py,
    candidate_labels,
    non_abstain_placeholder,
)


class TestBackendUnderTest(unittest.TestCase):
    def test_backend_under_test(self):
        self.assertIs(labels_mod._rust, _rust)
        if os.environ.get("PEIRA_NO_RUST"):
            self.assertIsNone(_rust, "PEIRA_NO_RUST=1 must force the reference backend")
        print(f"\nlabels parity backend: {'rust' if _rust is not None else 'python'}")


class TestCandidateLabelsParity(unittest.TestCase):
    def test_options_strings_sorted_deduped(self):
        case_input = {"options": ["deny", "approve", "deny", "escalate"]}
        expected = ["approve", "deny", "escalate", "other"]
        self.assertEqual(candidate_labels(case_input, "choice"), expected)
        self.assertEqual(_candidate_labels_py(case_input, "choice"), expected)

    def test_abstain_primitive_adds_abstain(self):
        case_input = {"options": ["approve", "deny"]}
        expected = ["abstain", "approve", "deny", "other"]
        self.assertEqual(candidate_labels(case_input, "abstain"), expected)
        self.assertEqual(_candidate_labels_py(case_input, "abstain"), expected)

    def test_missing_options(self):
        self.assertEqual(candidate_labels({}, "choice"), ["other"])
        self.assertEqual(candidate_labels({"options": None}, "score"), ["other"])

    def test_non_string_and_empty_options_ignored(self):
        case_input = {"options": ["approve", "", 42, None, ["x"], {"y": 1}, "deny"]}
        expected = ["approve", "deny", "other"]
        self.assertEqual(candidate_labels(case_input, "choice"), expected)
        self.assertEqual(_candidate_labels_py(case_input, "choice"), expected)

    def test_options_not_a_list(self):
        for options in ("approve", 42, {"a": 1}, ("approve", "deny")):
            self.assertEqual(candidate_labels({"options": options}, "choice"), ["other"])
            self.assertEqual(
                _candidate_labels_py({"options": options}, "choice"), ["other"]
            )

    def test_unicode_sort_order(self):
        # sorted() is codepoint order; the Rust core sorts byte-wise,
        # which agrees for valid UTF-8.
        options = ["zulu", "Äpfel", "éclair", "banana", "日本語"]
        expected = sorted(set(options) | {"other"})
        self.assertEqual(candidate_labels({"options": options}, "choice"), expected)
        self.assertEqual(_candidate_labels_py({"options": options}, "choice"), expected)

    def test_placeholder_not_duplicated(self):
        case_input = {"options": ["other", "approve", "other"]}
        self.assertEqual(candidate_labels(case_input, "choice"), ["approve", "other"])

    def test_non_dict_input_raises_attribute_error(self):
        # D-11: the wrapper does not dispatch on a non-dict; the
        # reference raises AttributeError calling .get.
        for bad in ("x", 42, ["options"], None):
            with self.assertRaises(AttributeError):
                candidate_labels(bad, "choice")
            with self.assertRaises(AttributeError):
                _candidate_labels_py(bad, "choice")

    def test_non_json_values_fall_back(self):
        # A set inside options is not JSON-shaped: the Rust path falls
        # back to the reference, which ignores the non-string entry.
        case_input = {"options": ["approve", {"a", "b"}]}
        expected = ["approve", "other"]
        self.assertEqual(candidate_labels(case_input, "choice"), expected)

    def test_fuzz_against_reference(self):
        rng = random.Random(20261001)
        primitives = ["choice", "score", "abstain", "other", ""]
        pool = ["approve", "deny", "", "escalate", "abstain", "other",
                42, None, ["nested"], {"k": "v"}, "Ünïcödé"]
        for _ in range(500):
            options = [rng.choice(pool) for _ in range(rng.randrange(6))]
            case_input = {"options": options}
            primitive = rng.choice(primitives)
            self.assertEqual(
                candidate_labels(case_input, primitive),
                _candidate_labels_py(case_input, primitive),
                f"options={options!r} primitive={primitive!r}",
            )


class TestNonAbstainPlaceholderParity(unittest.TestCase):
    def test_value(self):
        self.assertEqual(non_abstain_placeholder(), "other")
        self.assertEqual(non_abstain_placeholder(), NON_ABSTAIN_PLACEHOLDER)
        self.assertEqual(_non_abstain_placeholder_py(), "other")


if __name__ == "__main__":
    unittest.main()
