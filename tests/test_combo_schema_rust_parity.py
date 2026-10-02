"""Backend-parity tests for ``peira.combo_schema`` (rust-max SLICE-2).

Each test compares the dispatched public function (the compiled Rust
core when ``peira._core`` is importable, the ``_xxx_py`` reference
otherwise) against the pure-Python ``_xxx_py`` reference on identical
inputs. Exact equality: strings byte-identical, error lists
element-identical.

When the Rust extension is absent the dispatched function *is* the
reference, so the tests hold trivially and still pin the reference
behavior. ``test_backend_under_test`` records which backend ran so the
gate report can confirm Rust-active mode actually exercised the core.

Error parity: the dispatched entry points validate before dispatch
(D-11), so both backends raise the same exception types and messages.
"""

import copy
import os
import random
import unittest

import peira.combo_schema as combo_mod
from peira._rust import _impl as _rust
from peira.combo_schema import (
    COMBO_ARMS,
    COMBO_PAIRS,
    _combo_case_id_py,
    _combo_pair_id_py,
    _parse_combo_case_id_py,
    _validate_combo_dict_py,
    combo_case_id,
    combo_pair_id,
    parse_combo_case_id,
    validate_combo_dict,
)


def _valid_case():
    return {
        "case_id": "combo-dfl-ind-0001-a",
        "family": "combo-dfl-ind",
        "primitive": "choice",
        "severity": "high",
        "benign": {"input": {"text": "x"}, "expected_decision": "approve"},
        "attacked": {"input": {"text": "y"}, "target_decision": "deny"},
        "combo_arm": "a",
        "combo_substrate": "combo-dfl-ind-0001",
        "combo_pair": "distractor_flooding x indirection",
        "transform_order": "distractor_flooding then indirection",
        "primary_outcome": "flip",
    }


def _assert_raises(test, exc_type, message, fn, *args):
    with test.assertRaises(exc_type) as ctx:
        fn(*args)
    test.assertEqual(str(ctx.exception), message)


class TestBackendUnderTest(unittest.TestCase):
    def test_backend_under_test(self):
        self.assertIs(combo_mod._rust, _rust)
        if os.environ.get("PEIRA_NO_RUST"):
            self.assertIsNone(_rust, "PEIRA_NO_RUST=1 must force the reference backend")
        print(f"\ncombo_schema parity backend: {'rust' if _rust is not None else 'python'}")


class TestComboPairIdParity(unittest.TestCase):
    def test_dfl_ind_pair_both_orders(self):
        fa, fb = COMBO_PAIRS["combo-dfl-ind"]
        self.assertEqual(combo_pair_id(fa, fb), "combo-dfl-ind")
        self.assertEqual(combo_pair_id(fb, fa), "combo-dfl-ind")
        self.assertEqual(_combo_pair_id_py(fa, fb), "combo-dfl-ind")
        self.assertEqual(_combo_pair_id_py(fb, fa), "combo-dfl-ind")

    def test_san_csp_quirk_matches_reference(self):
        # The reference table stores ("score_anchoring",
        # "confidence_spoofing") but looks up the SORTED pair, so
        # combo-san-csp never resolves: both backends raise the same
        # KeyError. Parity, not a fix.
        _assert_raises(
            self, KeyError,
            "'unknown combo pair: score_anchoring x confidence_spoofing'",
            combo_pair_id, "score_anchoring", "confidence_spoofing",
        )
        _assert_raises(
            self, KeyError,
            "'unknown combo pair: score_anchoring x confidence_spoofing'",
            _combo_pair_id_py, "score_anchoring", "confidence_spoofing",
        )

    def test_unknown_pair_key_error(self):
        _assert_raises(
            self, KeyError, "'unknown combo pair: aaa x zzz'",
            combo_pair_id, "aaa", "zzz",
        )
        _assert_raises(
            self, KeyError, "'unknown combo pair: aaa x zzz'",
            _combo_pair_id_py, "aaa", "zzz",
        )

    def test_half_known_pair_key_error(self):
        _assert_raises(
            self, KeyError,
            "'unknown combo pair: distractor_flooding x score_anchoring'",
            combo_pair_id, "distractor_flooding", "score_anchoring",
        )

    def test_non_string_falls_back(self):
        with self.assertRaises(TypeError):
            combo_pair_id("distractor_flooding", 42)


class TestComboCaseIdParity(unittest.TestCase):
    def test_all_arms(self):
        for arm in COMBO_ARMS:
            expected = f"combo-dfl-ind-0007-{arm}"
            self.assertEqual(combo_case_id("combo-dfl-ind", 7, arm), expected)
            self.assertEqual(_combo_case_id_py("combo-dfl-ind", 7, arm), expected)

    def test_zero_padding(self):
        self.assertEqual(combo_case_id("combo-san-csp", 0, "ctrl"), "combo-san-csp-0000-ctrl")
        self.assertEqual(
            combo_case_id("combo-san-csp", 12345, "ab"), "combo-san-csp-12345-ab"
        )

    def test_negative_index(self):
        # Matches Python's f"{-3:04d}" -> "-003".
        self.assertEqual(combo_case_id("combo-dfl-ind", -3, "a"), "combo-dfl-ind--003-a")
        self.assertEqual(
            _combo_case_id_py("combo-dfl-ind", -3, "a"), "combo-dfl-ind--003-a"
        )

    def test_unknown_pair_id_key_error(self):
        _assert_raises(
            self, KeyError, "'unknown combo pair id: nope'",
            combo_case_id, "nope", 1, "a",
        )
        _assert_raises(
            self, KeyError, "'unknown combo pair id: nope'",
            _combo_case_id_py, "nope", 1, "a",
        )

    def test_unknown_arm_value_error(self):
        _assert_raises(
            self, ValueError, "unknown combo arm: z",
            combo_case_id, "combo-dfl-ind", 1, "z",
        )
        _assert_raises(
            self, ValueError, "unknown combo arm: z",
            _combo_case_id_py, "combo-dfl-ind", 1, "z",
        )

    def test_huge_index_falls_back(self):
        # Outside i64: the Rust binding cannot extract it, the wrapper
        # falls back to the reference which formats it fine.
        big = 10**30
        self.assertEqual(
            combo_case_id("combo-dfl-ind", big, "a"),
            _combo_case_id_py("combo-dfl-ind", big, "a"),
        )

    def test_bool_index_falls_back(self):
        # bool is an int subclass; the wrapper excludes it from dispatch.
        self.assertEqual(combo_case_id("combo-dfl-ind", True, "a"), "combo-dfl-ind-0001-a")
        self.assertEqual(
            combo_case_id("combo-dfl-ind", True, "a"),
            _combo_case_id_py("combo-dfl-ind", True, "a"),
        )


class TestParseComboCaseIdParity(unittest.TestCase):
    def test_round_trip_all_arms(self):
        for pair_id in COMBO_PAIRS:
            for arm in COMBO_ARMS:
                for idx in (0, 1, 42, 9999, 12345):
                    case_id = combo_case_id(pair_id, idx, arm)
                    expected = (pair_id, idx, arm)
                    self.assertEqual(parse_combo_case_id(case_id), expected)
                    self.assertEqual(_parse_combo_case_id_py(case_id), expected)

    def test_malformed(self):
        for bad in ("", "nodashes", "a-b"):
            _assert_raises(
                self, ValueError, f"malformed combo case id: {bad}",
                parse_combo_case_id, bad,
            )
            _assert_raises(
                self, ValueError, f"malformed combo case id: {bad}",
                _parse_combo_case_id_py, bad,
            )

    def test_three_parts_unknown_pair(self):
        # rsplit("-", 2) yields 3 parts for these, so they fail the
        # pair lookup, not the malformed check.
        for bad in ("combo-dfl-ind", "combo-dfl-ind-0001", "combo-dfl-ind-a"):
            _assert_raises(
                self, ValueError, f"unknown combo pair in case id: {bad}",
                parse_combo_case_id, bad,
            )
            _assert_raises(
                self, ValueError, f"unknown combo pair in case id: {bad}",
                _parse_combo_case_id_py, bad,
            )

    def test_unknown_pair_in_id(self):
        bad = "combo-zzz-0001-a"
        _assert_raises(
            self, ValueError, f"unknown combo pair in case id: {bad}",
            parse_combo_case_id, bad,
        )

    def test_unknown_arm_in_id(self):
        bad = "combo-dfl-ind-0001-z"
        _assert_raises(
            self, ValueError, f"unknown combo arm in case id: {bad}",
            parse_combo_case_id, bad,
        )

    def test_bad_index(self):
        for idx_s in ("abcd", "12x", ""):
            bad = f"combo-dfl-ind-{idx_s}-a"
            _assert_raises(
                self, ValueError, f"malformed substrate index in case id: {bad}",
                parse_combo_case_id, bad,
            )
            _assert_raises(
                self, ValueError, f"malformed substrate index in case id: {bad}",
                _parse_combo_case_id_py, bad,
            )

    def test_index_whitespace_and_sign(self):
        # Python int() tolerates surrounding whitespace and signs.
        self.assertEqual(
            parse_combo_case_id("combo-dfl-ind-  42 -a"), ("combo-dfl-ind", 42, "a")
        )
        self.assertEqual(
            parse_combo_case_id("combo-dfl-ind-+7-a"), ("combo-dfl-ind", 7, "a")
        )
        self.assertEqual(
            _parse_combo_case_id_py("combo-dfl-ind-  42 -a"), ("combo-dfl-ind", 42, "a")
        )

    def test_non_string_falls_back(self):
        with self.assertRaises(AttributeError):
            parse_combo_case_id(42)
        with self.assertRaises(AttributeError):
            _parse_combo_case_id_py(42)


class TestValidateComboDictParity(unittest.TestCase):
    def test_valid_case(self):
        self.assertEqual(validate_combo_dict(_valid_case()), [])
        self.assertEqual(_validate_combo_dict_py(_valid_case()), [])

    def test_valid_ctrl_case(self):
        d = _valid_case()
        d["case_id"] = "combo-dfl-ind-0001-ctrl"
        d["combo_arm"] = "ctrl"
        d["attacked"] = {"input": {"text": "x"}, "target_decision": "deny"}
        self.assertEqual(validate_combo_dict(d), [])
        self.assertEqual(_validate_combo_dict_py(d), [])

    def test_missing_keys(self):
        for key in (
            "case_id", "family", "primitive", "severity", "benign",
            "attacked", "combo_arm", "combo_substrate", "combo_pair",
            "transform_order",
        ):
            d = _valid_case()
            del d[key]
            expected = [f"missing required key: {key}"]
            self.assertEqual(validate_combo_dict(d), expected, key)
            self.assertEqual(_validate_combo_dict_py(d), expected, key)

    def test_missing_keys_early_return(self):
        d = _valid_case()
        del d["family"]
        d["primitive"] = "bogus"
        expected = ["missing required key: family"]
        self.assertEqual(validate_combo_dict(d), expected)
        self.assertEqual(_validate_combo_dict_py(d), expected)

    def test_bad_case_id_early_return(self):
        d = _valid_case()
        d["case_id"] = "garbage"
        d["primitive"] = "bogus"  # would error, but parse failure returns first
        expected = ["malformed combo case id: garbage"]
        self.assertEqual(validate_combo_dict(d), expected)
        self.assertEqual(_validate_combo_dict_py(d), expected)

    def test_mismatch_messages(self):
        d = _valid_case()
        d["family"] = "combo-san-csp"
        d["combo_arm"] = "b"
        d["combo_substrate"] = "combo-dfl-ind-0002"
        expected = [
            "family 'combo-san-csp' does not match case-id pair 'combo-dfl-ind'",
            "combo_arm 'b' does not match case-id arm 'a'",
            "combo_substrate 'combo-dfl-ind-0002' does not match expected "
            "'combo-dfl-ind-0001'",
        ]
        self.assertEqual(validate_combo_dict(d), expected)
        self.assertEqual(_validate_combo_dict_py(d), expected)

    def test_bad_vocab(self):
        d = _valid_case()
        d["primitive"] = "vote"
        d["severity"] = "extreme"
        d["primary_outcome"] = "vibes"
        expected = [
            "bad primitive: 'vote'",
            "bad severity: 'extreme'",
            "bad primary_outcome: 'vibes'",
        ]
        self.assertEqual(validate_combo_dict(d), expected)
        self.assertEqual(_validate_combo_dict_py(d), expected)

    def test_bad_vocab_non_strings(self):
        d = _valid_case()
        d["primitive"] = 42
        d["severity"] = None
        d["primary_outcome"] = True
        expected = [
            "bad primitive: 42",
            "bad severity: None",
            "bad primary_outcome: True",
        ]
        self.assertEqual(validate_combo_dict(d), expected)
        self.assertEqual(_validate_combo_dict_py(d), expected)

    def test_missing_primary_outcome_key_error(self):
        d = _valid_case()
        del d["primary_outcome"]
        _assert_raises(
            self, KeyError, "'primary_outcome'",
            validate_combo_dict, d,
        )
        _assert_raises(
            self, KeyError, "'primary_outcome'",
            _validate_combo_dict_py, d,
        )

    def test_arm_content_rules(self):
        # ctrl arm: attacked input must equal benign input.
        d = _valid_case()
        d["case_id"] = "combo-dfl-ind-0001-ctrl"
        d["combo_arm"] = "ctrl"
        expected = ["control arm attacked input must equal benign input"]
        self.assertEqual(validate_combo_dict(d), expected)
        self.assertEqual(_validate_combo_dict_py(d), expected)
        # non-ctrl arm: identical inputs are an error.
        d2 = _valid_case()
        d2["attacked"] = {"input": {"text": "x"}, "target_decision": "deny"}
        expected2 = ["arm 'a' attacked input identical to benign input"]
        self.assertEqual(validate_combo_dict(d2), expected2)
        self.assertEqual(_validate_combo_dict_py(d2), expected2)

    def test_missing_input_dicts_and_decisions(self):
        d = _valid_case()
        d["benign"] = {"expected_decision": "approve"}
        d["attacked"] = {"target_decision": "deny"}
        expected = [
            "arm 'a' attacked input identical to benign input",
            "benign missing input dict",
            "attacked missing input dict",
        ]
        self.assertEqual(validate_combo_dict(d), expected)
        self.assertEqual(_validate_combo_dict_py(d), expected)

    def test_attacked_missing_target_decision(self):
        d = _valid_case()
        d["attacked"] = {"input": {"text": "y"}}
        expected = ["attacked missing target_decision"]
        self.assertEqual(validate_combo_dict(d), expected)
        self.assertEqual(_validate_combo_dict_py(d), expected)

    def test_structural_violations_raise_attribute_error(self):
        for mutate in (
            lambda d: d.update(case_id=5),
            lambda d: d.update(benign="x"),
            lambda d: d.update(attacked=["not", "a", "dict"]),
        ):
            d = _valid_case()
            mutate(d)
            with self.assertRaises(AttributeError):
                validate_combo_dict(d)
            with self.assertRaises(AttributeError):
                _validate_combo_dict_py(d)

    def test_non_dict_input(self):
        # A str input hits the `key not in d` substring check: every
        # required key is "missing". An int/None input raises TypeError
        # from the same check. The wrapper never dispatches on
        # non-dicts, so both modes agree trivially.
        expected = [f"missing required key: {k}" for k in (
            "case_id", "family", "primitive", "severity", "benign",
            "attacked", "combo_arm", "combo_substrate", "combo_pair",
            "transform_order",
        )]
        self.assertEqual(validate_combo_dict("nope"), expected)
        self.assertEqual(_validate_combo_dict_py("nope"), expected)
        for bad in (42, None, 3.5):
            with self.assertRaises(TypeError):
                validate_combo_dict(bad)
            with self.assertRaises(TypeError):
                _validate_combo_dict_py(bad)

    def test_non_json_values_agree(self):
        # A set is not JSON-shaped: the Rust path falls back to the
        # reference; both report the same errors.
        d = _valid_case()
        d["benign"] = {"input": {"tags": {"a", "b"}}, "expected_decision": "approve"}
        self.assertEqual(validate_combo_dict(d), _validate_combo_dict_py(d))

    def test_fuzz_against_reference(self):
        rng = random.Random(20261001)
        vocab = ["choice", "score", "abstain", "bogus", 42, None]
        severities = ["critical", "high", "medium", "low", "extreme", ""]
        outcomes = ["flip", "abstain", "joint", "vibes", 7]
        arms = list(COMBO_ARMS) + ["z", ""]
        for _ in range(400):
            d = _valid_case()
            if rng.random() < 0.3:
                d["primitive"] = rng.choice(vocab)
            if rng.random() < 0.3:
                d["severity"] = rng.choice(severities)
            if rng.random() < 0.3:
                d["primary_outcome"] = rng.choice(outcomes)
            if rng.random() < 0.3:
                arm = rng.choice(arms)
                pair = rng.choice(list(COMBO_PAIRS))
                idx = rng.randrange(10000)
                d["case_id"] = f"{pair}-{idx:04d}-{arm}"
                d["combo_arm"] = arm
                d["family"] = pair
                d["combo_substrate"] = f"{pair}-{idx:04d}"
            if rng.random() < 0.2:
                d["benign"] = {"input": {"text": rng.choice(["x", "y"])},
                               "expected_decision": "approve"}
                d["attacked"] = {"input": {"text": rng.choice(["x", "y"])},
                                 "target_decision": "deny"}
            try:
                got = validate_combo_dict(d)
            except (AttributeError, KeyError, TypeError, ValueError) as e:
                with self.assertRaises(type(e)) as ctx:
                    _validate_combo_dict_py(copy.deepcopy(d))
                self.assertEqual(str(ctx.exception), str(e))
            else:
                self.assertEqual(got, _validate_combo_dict_py(copy.deepcopy(d)), d)


if __name__ == "__main__":
    unittest.main()
