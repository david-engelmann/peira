"""Backend parity for Rust migration lane 4 (unittest, not pytest).

Covers the lane-4 ports, each as dispatcher-vs-``_xxx_py`` parity plus
independently computed known vectors:

- ``peira.artifacts.RunArtifact.compute_lock`` (priority 1)
- ``peira.runner`` record helpers: ``_blank_record``,
  ``_record_from_transcript_entry``, ``_output_to_dict``,
  ``_output_from_dict`` (priority 2)
- ``peira.dataset._summarize_bytes`` (priority 3)
- ``peira.concurrency.validate_transcript_entry``
- ``peira.pricing.cost_usd``
- ``peira.env_fingerprint.fingerprint_env``

(There is no ``report.py`` at this commit; report computation lives in
``peira.metrics``, ported in lane 1.)

The parity tests pass whether or not ``peira._core`` is built. Tests
that pin down Rust-boundary behavior (exception types raised by the
extension itself) skip when it is absent.
"""

import dataclasses
import hashlib
import json
import math
import random
import typing
import unittest

from peira import _rust
from peira.adapters.base import (
    AbstainOutput,
    CallUsage,
    ChoiceOutput,
    ScoreOutput,
)
from peira.artifacts import RunArtifact
from peira.concurrency import (
    validate_transcript_entry,
    validate_transcript_entry_py,
)
from peira.dataset import _summarize_bytes, _summarize_bytes_py
from peira.env_fingerprint import fingerprint_env, fingerprint_env_py
from peira.metrics import CallRecord
from peira.pricing import cost_usd, cost_usd_py
from peira.runner import (
    _blank_record,
    _blank_record_py,
    _output_from_dict,
    _output_from_dict_py,
    _output_to_dict,
    _output_to_dict_py,
    _record_from_transcript_entry,
    _record_from_transcript_entry_py,
)

FAMILIES = [
    "state_poisoning",
    "criteria_smuggling",
    "option_order",
    "literal_reading",
]
SEVERITIES = ["critical", "high", "medium", "low"]
PRIMITIVES = ["choice", "score", "abstain"]


def make_case(i, family="state_poisoning", severity="high", primitive="choice"):
    """One minimal schema-valid case dict."""
    return {
        "case_id": f"t-{i:04d}",
        "family": family,
        "primitive": primitive,
        "severity": severity,
        "benign": {
            "input": {"prompt": "decide", "options": ["approve", "deny"]},
            "expected_decision": "deny",
        },
        "attacked": {
            "input": {"prompt": "decide!", "options": ["approve", "deny"]},
            "target_decision": "approve",
        },
    }


def make_usage():
    return {
        "model": "hf:test",
        "tokens_in": 10,
        "tokens_out": 3,
        "latency_ms": 12.5,
        "cost_usd": 0.0001,
    }


def make_entry(**over):
    entry = {
        "seed": 7,
        "dispatch_index": 3,
        "dispatch_limit": 4,
        "primitive": "choice",
        "response": {
            "kind": "output",
            "output": {
                "decision": "approve",
                "confidence": 0.9,
                "abstained": False,
                "refusal_reason": "",
                "usage": make_usage(),
            },
        },
    }
    entry.update(over)
    return entry


def make_transcript_entry(**over):
    entry = {
        "dispatch_index": 0,
        "case_id": "t-0001",
        "variant": "benign",
        "primitive": "choice",
        "request": {"prompt": "hi"},
        "response": {"kind": "output", "output": {"decision": "approve"}},
        "provider": {"adapter_name": "dummy"},
        "seed": 7,
        "dispatch_limit": 4,
        "max_concurrency": 8,
    }
    entry.update(over)
    return entry


class ComputeLockParity(unittest.TestCase):
    def make_artifact(self, **over):
        kw = dict(
            dataset_version="1.0",
            adapter_name="dummy",
            adapter_version="0",
            suite="trial-demo",
            config={"k": [1, 2, {"n": None}]},
            results=[{"case_id": "c1", "x": 1.5}],
            metrics={"asr": 0.25},
            seed=7,
            max_concurrency=8,
            manifest_sha256="abc",
            pricing_source="s",
            pricing_date="2026-01-01",
            env_sha256="def",
        )
        kw.update(over)
        return RunArtifact(**kw)

    def test_known_vector_independent(self):
        """Lock matches a digest computed directly with hashlib/json."""
        a = self.make_artifact()
        payload = json.dumps(
            {
                "peira_version": a.peira_version,
                "dataset_version": "1.0",
                "adapter_name": "dummy",
                "adapter_version": "0",
                "suite": "trial-demo",
                "config": {"k": [1, 2, {"n": None}]},
                "results": [{"case_id": "c1", "x": 1.5}],
                "manifest_sha256": "abc",
                "pricing_source": "s",
                "pricing_date": "2026-01-01",
                "pricing_version": "",
                "contract_version": "1",
                "termination": "complete",
                "budget_usd": None,
                "spent_usd": 0.0,
                "cases_completed": 0,
                "cases_planned": 0,
                "seed": 7,
                "max_concurrency": 8,
                "metrics": {"asr": 0.25},
                "env_sha256": "def",
            },
            sort_keys=True,
        )
        expected = hashlib.sha256(payload.encode()).hexdigest()
        self.assertEqual(a.compute_lock(), expected)
        self.assertEqual(a._compute_lock_py(), expected)

    def test_unicode_nesting_floats(self):
        a = self.make_artifact(
            config={
                "u": "héllo→\U0001f600",
                "nest": {"a": [True, False, None, 1.5, 1e300, -0.0]},
                "empty": {},
                "s": "quote\"back\\slash\nnewline\ttab",
            },
            results=[],
            metrics={"m": {"deep": [1, {"x": None}]}},
        )
        self.assertEqual(a.compute_lock(), a._compute_lock_py())

    def test_randomized(self):
        rng = random.Random(20260927)
        for trial in range(50):
            config = {
                f"k{i}": rng.choice(
                    [
                        None,
                        True,
                        rng.randint(-10**6, 10**6),
                        rng.uniform(-1000, 1000),
                        "".join(
                            rng.choice("abé→") for _ in range(rng.randint(0, 8))
                        ),
                        [rng.randint(0, 9) for _ in range(rng.randint(0, 4))],
                        {"n": rng.randint(0, 9)},
                    ]
                )
                for i in range(rng.randint(0, 6))
            }
            a = self.make_artifact(
                config=config,
                seed=rng.randint(0, 2**40),
                metrics={"v": rng.uniform(0, 1)},
            )
            self.assertEqual(
                a.compute_lock(), a._compute_lock_py(), f"trial {trial}"
            )

    def test_seal_verify_roundtrip(self):
        a = self.make_artifact().seal()
        self.assertTrue(a.verify())

    def test_huge_seed_falls_back(self):
        # Seed past i64: OverflowError at the binding boundary, so the
        # pure-Python fallback computes the lock.
        a = self.make_artifact(seed=2**70)
        self.assertEqual(a.compute_lock(), a._compute_lock_py())

    def test_huge_max_concurrency_falls_back(self):
        a = self.make_artifact(max_concurrency=2**70)
        self.assertEqual(a.compute_lock(), a._compute_lock_py())

    def test_bool_seed_falls_back(self):
        # PyO3 coerces bool to int silently; the reference serializes
        # True as `true`. The binding must reject bool so the fallback
        # computes the reference digest.
        a = self.make_artifact(seed=True)
        self.assertEqual(a.compute_lock(), a._compute_lock_py())
        self.assertIs(a.seed, True)
        # ...and the bool digest differs from the coerced-int digest.
        self.assertNotEqual(
            a.compute_lock(), self.make_artifact(seed=1).compute_lock()
        )


class BlankRecordParity(unittest.TestCase):
    def test_shape(self):
        r = _blank_record(7, 3, 4)
        self.assertEqual(r.decision, "<error>")
        self.assertIsNone(r.confidence)
        self.assertFalse(r.abstained)
        self.assertTrue(r.malformed)
        self.assertEqual((r.seed, r.dispatch_index, r.dispatch_limit), (7, 3, 4))
        self.assertIsNone(r.usage)
        self.assertIsNone(r.score)

    def test_randomized(self):
        rng = random.Random(20260927)
        for _ in range(200):
            seed = rng.randint(0, 2**31 - 1)
            idx = rng.randint(0, 10**6)
            lim = rng.randint(1, 64)
            self.assertEqual(
                _blank_record(seed, idx, lim), _blank_record_py(seed, idx, lim)
            )

    def test_wrong_typed_seed_falls_back(self):
        # The i64 binding raises TypeError for a float seed; the
        # reference stores it as-is. No try/except meant no fallback.
        self.assertEqual(
            _blank_record(3.7, 0, 1), _blank_record_py(3.7, 0, 1)
        )

    def test_huge_seed_falls_back(self):
        # Seed past i64: the binding raises OverflowError (not
        # TypeError); the reference handles arbitrary precision.
        self.assertEqual(
            _blank_record(2**70, 0, 1), _blank_record_py(2**70, 0, 1)
        )

    def test_bool_seed_falls_back(self):
        # A bool seed is not an int seed: PyO3 would coerce True to 1
        # silently, but the reference stores True as-is. The binding
        # raises TypeError so the fallback preserves the bool.
        got = _blank_record(True, 0, 1)
        want = _blank_record_py(True, 0, 1)
        self.assertEqual(got, want)
        self.assertIs(got.seed, True)
        self.assertIs(want.seed, True)

    def test_bool_dispatch_index_falls_back(self):
        got = _blank_record(7, True, 1)
        self.assertEqual(got, _blank_record_py(7, True, 1))
        self.assertIs(got.dispatch_index, True)


class RecordFromTranscriptEntryParity(unittest.TestCase):
    def assertParity(self, entry):
        """Both backends agree — value or exact exception."""
        try:
            want = _record_from_transcript_entry_py(entry)
            want_exc = None
        except Exception as e:  # noqa: BLE001
            want, want_exc = None, e
        try:
            got = _record_from_transcript_entry(entry)
            got_exc = None
        except Exception as e:  # noqa: BLE001
            got, got_exc = None, e
        if want_exc is not None or got_exc is not None:
            self.assertIsNotNone(want_exc, f"py ok but dispatch raised {got_exc!r}")
            self.assertIsNotNone(got_exc, f"dispatch ok but py raised {want_exc!r}")
            self.assertEqual(type(want_exc), type(got_exc))
            self.assertEqual(str(want_exc), str(got_exc))
        else:
            self.assertEqual(got, want)

    def test_output_entry(self):
        r = _record_from_transcript_entry(make_entry())
        self.assertIsInstance(r, CallRecord)
        self.assertEqual(r.decision, "approve")
        self.assertEqual(r.confidence, 0.9)
        self.assertFalse(r.malformed)
        self.assertEqual(r.usage.tokens_in, 10)
        self.assertIsNone(r.score)
        self.assertParity(make_entry())

    def test_error_entry_rebuilds_blank(self):
        entry = make_entry(response={"kind": "error", "detail": "boom"})
        r = _record_from_transcript_entry(entry)
        self.assertEqual(r.decision, "<error>")
        self.assertTrue(r.malformed)
        self.assertEqual(r.seed, 7)
        self.assertParity(entry)

    def test_non_mapping_response_is_typeerror(self):
        # The reference subscripts response["kind"]: a non-mapping
        # response is TypeError there, not KeyError.
        for bad in ("not-a-mapping", None, [1, 2], 42):
            entry = make_entry(response=bad)
            with self.assertRaises(TypeError):
                _record_from_transcript_entry_py(entry)
            self.assertParity(entry)

    def test_non_object_output_is_attributeerror(self):
        # The reference calls out.get("usage"): a non-object output is
        # AttributeError there, not KeyError.
        entry = make_entry(response={"kind": "output", "output": [1, 2]})
        with self.assertRaises(AttributeError):
            _record_from_transcript_entry_py(entry)
        self.assertParity(entry)

    def test_non_mapping_entry_is_typeerror(self):
        # The reference subscripts entry["seed"]: a non-dict entry is
        # TypeError there, not KeyError — with CPython's exact message.
        for bad in ([1, 2], None, "x", 42):
            with self.assertRaises(TypeError) as c1:
                _record_from_transcript_entry_py(bad)
            with self.assertRaises(TypeError) as c2:
                _record_from_transcript_entry(bad)
            self.assertEqual(str(c1.exception), str(c2.exception), f"{bad!r}")
            self.assertParity(bad)

    def test_score_preserved_only_on_score_primitive(self):
        out = {
            "decision": "approve",
            "confidence": 0.8,
            "abstained": False,
            "refusal_reason": "",
            "usage": None,
            "score": 0.75,
        }
        entry = make_entry(primitive="score", response={"kind": "output", "output": out})
        self.assertEqual(_record_from_transcript_entry(entry).score, 0.75)
        self.assertParity(entry)
        # Same entry on a non-score primitive: the foreign score must not leak.
        entry2 = make_entry(response={"kind": "output", "output": out})
        self.assertIsNone(_record_from_transcript_entry(entry2).score)
        self.assertParity(entry2)

    def test_usage_absent(self):
        out = {
            "decision": "deny",
            "confidence": None,
            "abstained": True,
            "refusal_reason": "policy",
            "usage": None,
        }
        entry = make_entry(response={"kind": "output", "output": out})
        r = _record_from_transcript_entry(entry)
        self.assertIsNone(r.usage)
        self.assertIsNone(r.confidence)
        self.assertTrue(r.abstained)
        self.assertEqual(r.refusal_reason, "policy")
        self.assertParity(entry)

    def test_defaulted_optionals(self):
        entry = make_entry(
            response={"kind": "output", "output": {"decision": "approve"}}
        )
        r = _record_from_transcript_entry(entry)
        self.assertIsNone(r.confidence)
        self.assertFalse(r.abstained)
        self.assertEqual(r.refusal_reason, "")
        self.assertIsNone(r.usage)
        self.assertParity(entry)

    def test_missing_keys_raise_keyerror(self):
        for key in ("seed", "dispatch_index", "dispatch_limit", "response"):
            entry = make_entry()
            del entry[key]
            with self.assertRaises(KeyError):
                _record_from_transcript_entry_py(entry)
            self.assertParity(entry)

    def test_int_coercion(self):
        entry = make_entry(seed="7", dispatch_index="3", dispatch_limit="4")
        self.assertParity(entry)
        self.assertEqual(_record_from_transcript_entry(entry).seed, 7)

    def test_weird_but_passthrough_values(self):
        # Python passes confidence/decision/score through unvalidated;
        # the dispatcher must too (via fallback).
        out = {
            "decision": "approve",
            "confidence": "high",
            "abstained": False,
            "refusal_reason": "",
            "usage": None,
        }
        self.assertParity(
            make_entry(response={"kind": "output", "output": out})
        )
        out2 = dict(out, score="0.5")
        self.assertParity(
            make_entry(
                primitive="score",
                response={"kind": "output", "output": out2},
            )
        )

    def test_int_confidence_preserved_exactly(self):
        # The Rust core stores confidence as f64 and would coerce int 1
        # to 1.0; the reference passes it through untouched. Both
        # backends must keep the int (repr-level: "1", not "1.0").
        out = {
            "decision": "approve",
            "confidence": 1,
            "abstained": False,
            "refusal_reason": "",
            "usage": None,
        }
        entry = make_entry(response={"kind": "output", "output": out})
        self.assertEqual(repr(_record_from_transcript_entry(entry).confidence), "1")
        self.assertEqual(
            repr(_record_from_transcript_entry_py(entry).confidence), "1"
        )
        self.assertParity(entry)

    def test_huge_int_confidence_preserved(self):
        # 2**63 as f64 loses precision; the dispatcher must not coerce.
        out = {
            "decision": "approve",
            "confidence": 2**63,
            "abstained": False,
            "refusal_reason": "",
            "usage": None,
        }
        entry = make_entry(response={"kind": "output", "output": out})
        r = _record_from_transcript_entry(entry)
        self.assertIsInstance(r.confidence, int)
        self.assertEqual(r.confidence, 2**63)
        self.assertParity(entry)

    def test_int_score_on_score_primitive_preserved(self):
        out = {
            "decision": "approve",
            "confidence": 0.8,
            "abstained": False,
            "refusal_reason": "",
            "usage": None,
            "score": 2,
        }
        entry = make_entry(
            primitive="score", response={"kind": "output", "output": out}
        )
        self.assertEqual(repr(_record_from_transcript_entry(entry).score), "2")
        self.assertParity(entry)

    def test_non_mapping_entry_exact_cpython_messages(self):
        # bytearray/range/array/memoryview have their own CPython
        # subscript messages; the dispatcher must match exactly.
        import array

        cases = [
            (bytearray(b"z"), "bytearray indices must be integers or slices, not str"),
            (range(3), "range indices must be integers or slices, not str"),
            (array.array("i", [1]), "array indices must be integers"),
            (memoryview(b"z"), "memoryview: invalid slice key"),
            (b"z", "byte indices must be integers or slices, not str"),
        ]
        for bad, want in cases:
            with self.assertRaises(TypeError) as c1:
                _record_from_transcript_entry_py(bad)
            with self.assertRaises(TypeError) as c2:
                _record_from_transcript_entry(bad)
            self.assertEqual(str(c1.exception), want, repr(bad))
            self.assertEqual(str(c2.exception), want, repr(bad))
            self.assertParity(bad)

    def test_randomized(self):
        rng = random.Random(20260927)
        for trial in range(300):
            primitive = rng.choice(PRIMITIVES + ["choice"])
            out = {
                "decision": rng.choice(["approve", "deny", "abstain"]),
                "confidence": rng.choice([None, 0.0, 0.5, 1.0]),
                "abstained": rng.choice([True, False]),
                "refusal_reason": rng.choice(["", "policy"]),
                "usage": rng.choice([None, make_usage()]),
            }
            if primitive == "score":
                out["score"] = rng.uniform(0, 1)
            elif rng.random() < 0.1:
                out["score"] = rng.uniform(0, 1)  # foreign score
            kind = rng.choice(["output", "output", "error"])
            response = (
                {"kind": "output", "output": out}
                if kind == "output"
                else {"kind": "error", "detail": "x"}
            )
            entry = {
                "seed": rng.randint(0, 9999),
                "dispatch_index": rng.randint(0, 999),
                "dispatch_limit": rng.randint(1, 32),
                "primitive": primitive,
                "response": response,
            }
            try:
                want = _record_from_transcript_entry_py(entry)
            except Exception as e:  # noqa: BLE001
                want_exc = e
            else:
                want_exc = None
            try:
                got = _record_from_transcript_entry(entry)
            except Exception as e:  # noqa: BLE001
                got, got_exc = None, e
            else:
                got_exc = None
            if want_exc is not None or got_exc is not None:
                self.assertEqual(
                    type(want_exc), type(got_exc), f"trial {trial}: {entry}"
                )
            else:
                self.assertEqual(got, want, f"trial {trial}: {entry}")


class OutputDictParity(unittest.TestCase):
    def test_to_dict_exact_keys(self):
        out = ChoiceOutput(
            decision="deny",
            confidence=0.4,
            usage=CallUsage(
                model="m", tokens_in=1, tokens_out=2, latency_ms=3.0, cost_usd=0.0
            ),
        )
        d = _output_to_dict(out, "choice")
        self.assertEqual(
            sorted(d), ["abstained", "confidence", "decision", "refusal_reason", "usage"]
        )
        self.assertNotIn("score", d)
        self.assertNotIn("extra", d)
        self.assertEqual(d, _output_to_dict_py(out, "choice"))

    def test_to_dict_score_primitive(self):
        out = ScoreOutput(decision="approve", confidence=0.8, score=0.75, usage=None)
        d = _output_to_dict(out, "score")
        self.assertEqual(d["score"], 0.75)
        self.assertIsNone(d["usage"])
        self.assertEqual(d, _output_to_dict_py(out, "score"))

    def test_to_dict_missing_attr_raises_attributeerror(self):
        with self.assertRaises(AttributeError):
            _output_to_dict_py(object(), "choice")
        with self.assertRaises(AttributeError):
            _output_to_dict(object(), "choice")

    def test_dict_usage_is_typeerror(self):
        # The reference runs dataclasses.asdict on the usage: a dict is
        # not a dataclass, so TypeError — both backends.
        out = dataclasses.replace(
            ChoiceOutput(decision="deny", confidence=0.4, usage=None),
            usage={"model": "m"},
        )
        with self.assertRaises(TypeError):
            _output_to_dict_py(out, "choice")
        with self.assertRaises(TypeError):
            _output_to_dict(out, "choice")

    def test_from_dict_roundtrip(self):
        for primitive, out in [
            ("choice", ChoiceOutput(decision="deny", confidence=0.4, usage=None)),
            (
                "score",
                ScoreOutput(decision="approve", confidence=0.8, score=0.2, usage=None),
            ),
            ("abstain", AbstainOutput(decision="abstain", usage=None)),
        ]:
            d = _output_to_dict(out, primitive)
            back = _output_from_dict(primitive, d)
            self.assertEqual(back, _output_from_dict_py(primitive, d))
            self.assertEqual(back, out)

    def test_from_dict_defaults(self):
        back = _output_from_dict("abstain", {"decision": "abstain"})
        self.assertFalse(back.abstained)
        self.assertEqual(back.refusal_reason, "")
        self.assertIsNone(back.usage)
        self.assertIsNone(back.confidence)
        self.assertEqual(back, _output_from_dict_py("abstain", {"decision": "abstain"}))

    def test_from_dict_unknown_primitive(self):
        with self.assertRaises(ValueError):
            _output_from_dict_py("nope", {"decision": "x"})
        with self.assertRaises(ValueError):
            _output_from_dict("nope", {"decision": "x"})

    def test_from_dict_wrong_shapes(self):
        # Wrong-shaped dicts are cache misses: KeyError/TypeError, both backends.
        for d in (
            {},
            {"decision": "x", "usage": {"bogus": 1}},
            {"decision": "x", "usage": {"model": "m"}},
            {"confidence": 0.5},
        ):
            for fn, ref in (
                (_output_from_dict, _output_from_dict_py),
            ):
                try:
                    ref("choice", d)
                    ref_exc = None
                except Exception as e:  # noqa: BLE001
                    ref_exc = e
                try:
                    fn("choice", d)
                    exc = None
                except Exception as e:  # noqa: BLE001
                    exc = e
                self.assertIsNotNone(ref_exc, f"py accepted {d}")
                self.assertIsNotNone(exc, f"dispatch accepted {d}")
                self.assertEqual(type(ref_exc), type(exc), f"{d}")

    def test_from_dict_score_required(self):
        d = {
            "decision": "approve",
            "confidence": 0.9,
            "abstained": False,
            "refusal_reason": "",
            "usage": None,
        }
        with self.assertRaises(KeyError):
            _output_from_dict("score", d)
        d["score"] = 0.3
        self.assertEqual(_output_from_dict("score", d).score, 0.3)

    def test_from_dict_explicit_none_optionals(self):
        # Explicit null is not the missing-key default: the reference
        # passes None through (d.get("abstained", False) -> None).
        d = {"decision": "approve", "abstained": None, "refusal_reason": None}
        back = _output_from_dict("choice", d)
        want = _output_from_dict_py("choice", d)
        self.assertIsNone(back.abstained)
        self.assertIsNone(back.refusal_reason)
        self.assertEqual(back, want)
        # Missing keys still default to False / "".
        back2 = _output_from_dict("choice", {"decision": "approve"})
        self.assertFalse(back2.abstained)
        self.assertEqual(back2.refusal_reason, "")
        self.assertEqual(back2, _output_from_dict_py("choice", {"decision": "approve"}))

    def test_from_dict_non_dict_d_is_attributeerror(self):
        # The reference calls d.get("usage"): a non-dict d is
        # AttributeError there, not KeyError — uncaught on both backends.
        for bad in ([1, 2], None, "x", 42):
            with self.assertRaises(AttributeError) as c1:
                _output_from_dict_py("choice", bad)
            with self.assertRaises(AttributeError) as c2:
                _output_from_dict("choice", bad)
            self.assertEqual(str(c1.exception), str(c2.exception), f"{bad!r}")

    def test_duck_typed_usage_is_typeerror(self):
        # The reference runs dataclasses.asdict on the usage: any
        # non-dataclass object (not just dicts) is TypeError.
        class DuckUsage:
            model = "m"
            tokens_in = 1
            tokens_out = 2
            latency_ms = 1.0
            cost_usd = 0.0

        out = ChoiceOutput(decision="approve", confidence=0.5, usage=None)
        out = dataclasses.replace(out, usage=DuckUsage())
        with self.assertRaises(TypeError) as c1:
            _output_to_dict_py(out, "choice")
        with self.assertRaises(TypeError) as c2:
            _output_to_dict(out, "choice")
        self.assertEqual(str(c1.exception), str(c2.exception))

    def test_dataclass_class_usage_is_typeerror(self):
        # A dataclass *class* (not instance): the reference's asdict
        # raises TypeError on classes — both backends, same message.
        out = ChoiceOutput(decision="deny", confidence=0.4, usage=None)
        out = dataclasses.replace(out, usage=CallUsage)
        with self.assertRaises(TypeError) as c1:
            _output_to_dict_py(out, "choice")
        with self.assertRaises(TypeError) as c2:
            _output_to_dict(out, "choice")
        self.assertEqual(str(c1.exception), str(c2.exception))

    def test_foreign_dataclass_usage_keeps_extra_fields(self):
        # A foreign dataclass with fields beyond the five known CallUsage
        # fields: the reference's asdict preserves every field, so the
        # dispatcher must fall back and keep them all.
        @dataclasses.dataclass
        class ForeignUsage:
            model: str = "m"
            tokens_in: int = 1
            tokens_out: int = 2
            latency_ms: float = 3.0
            cost_usd: float = 0.0
            extra: str = "kept"

        out = ChoiceOutput(decision="deny", confidence=0.4, usage=None)
        out = dataclasses.replace(out, usage=ForeignUsage())
        d = _output_to_dict(out, "choice")
        self.assertEqual(d["usage"]["extra"], "kept")
        self.assertEqual(d, _output_to_dict_py(out, "choice"))

    def test_bool_usage_token_fields_preserved(self):
        # tokens_in=True: Rust extraction would coerce to 1, but the
        # reference's asdict keeps True. The dispatcher must fall back.
        usage = CallUsage(
            model="m", tokens_in=True, tokens_out=2, latency_ms=3.0, cost_usd=0.0
        )
        out = ChoiceOutput(decision="deny", confidence=0.4, usage=usage)
        d = _output_to_dict(out, "choice")
        self.assertIs(d["usage"]["tokens_in"], True)
        self.assertEqual(d, _output_to_dict_py(out, "choice"))

    def test_int_usage_float_fields_preserved(self):
        # latency_ms=5: Rust extraction would coerce to 5.0, but the
        # reference's asdict keeps 5. The dispatcher must fall back.
        usage = CallUsage(
            model="m", tokens_in=1, tokens_out=2, latency_ms=5, cost_usd=1
        )
        out = ChoiceOutput(decision="deny", confidence=0.4, usage=usage)
        d = _output_to_dict(out, "choice")
        self.assertEqual(repr(d["usage"]["latency_ms"]), "5")
        self.assertEqual(repr(d["usage"]["cost_usd"]), "1")
        self.assertEqual(d, _output_to_dict_py(out, "choice"))

    def test_nonfinite_usage_float_fields_preserved(self):
        # latency_ms=nan: serde_json would silently serialize it as null
        # on the Rust path, but the reference's asdict preserves nan.
        # The dispatcher must fall back so both backends agree exactly.
        for field in ("latency_ms", "cost_usd"):
            for value in (float("nan"), float("inf"), float("-inf")):
                kw = dict(
                    model="m", tokens_in=1, tokens_out=2,
                    latency_ms=3.0, cost_usd=0.0,
                )
                kw[field] = value
                usage = CallUsage(**kw)
                out = ChoiceOutput(decision="deny", confidence=0.4, usage=usage)
                d = _output_to_dict(out, "choice")
                ref = _output_to_dict_py(out, "choice")
                got, want = d["usage"][field], ref["usage"][field]
                if math.isnan(value):
                    self.assertTrue(math.isnan(got), f"{field}={value}")
                    self.assertTrue(math.isnan(want), f"ref {field}={value}")
                else:
                    self.assertEqual(got, value)
                    self.assertEqual(got, want)
                for k, v in ref["usage"].items():
                    if k != field:
                        self.assertEqual(d["usage"][k], v)

    def test_foreign_dataclass_subset_fields_preserved(self):
        # A foreign dataclass with a SUBSET of the five known CallUsage
        # fields: the reference's asdict serializes it fine, but the Rust
        # projection would die with AttributeError. The dispatcher must
        # fall back and keep the fields it has.
        @dataclasses.dataclass
        class ForeignFewer:
            model: str = "m"
            tokens_in: int = 1
            tokens_out: int = 2
            latency_ms: float = 3.0

        out = ChoiceOutput(decision="deny", confidence=0.4, usage=None)
        out = dataclasses.replace(out, usage=ForeignFewer())
        d = _output_to_dict(out, "choice")
        self.assertEqual(
            d["usage"],
            {"model": "m", "tokens_in": 1, "tokens_out": 2, "latency_ms": 3.0},
        )
        self.assertEqual(d, _output_to_dict_py(out, "choice"))

    def test_foreign_dataclass_pseudo_fields_fall_back(self):
        # A foreign dataclass with exactly the five known field names where
        # one is a ClassVar/InitVar pseudo-field: dataclasses.fields() (and
        # hence asdict) excludes pseudo-fields, so the reference serializes
        # four fields while the Rust projection would serialize five. The
        # dispatcher must reject the shape (TypeError -> fallback) and
        # match the reference exactly.
        @dataclasses.dataclass
        class ForeignClassVar:
            model: typing.ClassVar[str] = "m"
            tokens_in: int = 1
            tokens_out: int = 2
            latency_ms: float = 3.0
            cost_usd: float = 0.0

        @dataclasses.dataclass
        class ForeignInitVar:
            cost_usd: dataclasses.InitVar[float] = 0.0
            model: str = "m"
            tokens_in: int = 1
            tokens_out: int = 2
            latency_ms: float = 3.0

        for cls in (ForeignClassVar, ForeignInitVar):
            out = ChoiceOutput(decision="deny", confidence=0.4, usage=None)
            out = dataclasses.replace(out, usage=cls())
            d = _output_to_dict(out, "choice")
            ref = _output_to_dict_py(out, "choice")
            self.assertEqual(len(ref["usage"]), 4, cls.__name__)
            self.assertEqual(d, ref, cls.__name__)

    def test_unbound_field_fakes_rejected(self):
        # A non-dataclass with a hand-made __dataclass_fields__ of unbound
        # dataclasses.field() objects: each fake carries _field_type=None,
        # so only an identity check against dataclasses._FIELD rejects them.
        # The dispatcher must fall back to the reference (which returns {}).
        class FakeFields:
            __dataclass_fields__ = {
                name: dataclasses.field() for name in (
                    "model", "tokens_in", "tokens_out", "latency_ms", "cost_usd"
                )
            }

        out = ChoiceOutput(decision="deny", confidence=0.4, usage=None)
        out = dataclasses.replace(out, usage=FakeFields())
        d = _output_to_dict(out, "choice")
        ref = _output_to_dict_py(out, "choice")
        self.assertEqual(ref["usage"], {})
        self.assertEqual(d, ref)

    def test_instance_attr_dataclass_fields_is_typeerror(self):
        # An instance-level __dataclass_fields__ does not make a dataclass:
        # CPython's asdict gates on the *class* attribute. Both backends
        # must raise TypeError with the identical message.
        class FakeUsage:
            def __init__(self):
                self.__dataclass_fields__ = {}

        out = ChoiceOutput(decision="deny", confidence=0.4, usage=None)
        out = dataclasses.replace(out, usage=FakeUsage())
        with self.assertRaises(TypeError) as c1:
            _output_to_dict_py(out, "choice")
        with self.assertRaises(TypeError) as c2:
            _output_to_dict(out, "choice")
        self.assertEqual(str(c1.exception), str(c2.exception))

    def test_bool_confidence_preserved(self):
        # confidence=True round-trips natively through value_from_py /
        # value_to_py on both paths (no fallback involved); the bool must
        # surface untouched and identical on both backends.
        out = ChoiceOutput(decision="deny", confidence=True, usage=None)
        d = _output_to_dict(out, "choice")
        self.assertIs(d["confidence"], True)
        self.assertEqual(d, _output_to_dict_py(out, "choice"))

    def test_from_dict_int_confidence_preserved(self):
        # The Rust core stores confidence as f64 and would coerce int 1
        # to 1.0; the reference passes it through untouched.
        d = {"decision": "x", "confidence": 1}
        back = _output_from_dict("choice", d)
        self.assertEqual(repr(back.confidence), "1")
        self.assertEqual(back, _output_from_dict_py("choice", d))

    def test_from_dict_huge_int_confidence_preserved(self):
        # 2**63 as f64 loses precision; the dispatcher must not coerce.
        d = {"decision": "x", "confidence": 2**63}
        back = _output_from_dict("choice", d)
        self.assertIsInstance(back.confidence, int)
        self.assertEqual(back.confidence, 2**63)
        self.assertEqual(back, _output_from_dict_py("choice", d))

    def test_from_dict_int_score_preserved(self):
        d = {"decision": "x", "confidence": 0.5, "score": 2}
        back = _output_from_dict("score", d)
        self.assertEqual(repr(back.score), "2")
        self.assertEqual(back, _output_from_dict_py("score", d))


class ValidateTranscriptEntryParity(unittest.TestCase):
    def assertParity(self, entry, lineno=1):
        try:
            want = validate_transcript_entry_py(entry, lineno)
            want_exc = None
        except Exception as e:  # noqa: BLE001
            want, want_exc = None, e
        try:
            got = validate_transcript_entry(entry, lineno)
            got_exc = None
        except Exception as e:  # noqa: BLE001
            got, got_exc = None, e
        if want_exc is not None or got_exc is not None:
            self.assertIsNotNone(want_exc)
            self.assertIsNotNone(got_exc)
            self.assertEqual(type(want_exc), type(got_exc), f"{entry}")
            self.assertEqual(str(want_exc), str(got_exc), f"{entry}")
        else:
            self.assertEqual(got, want)

    def test_valid(self):
        entry = make_transcript_entry()
        self.assertEqual(validate_transcript_entry(entry, 1), entry)
        self.assertParity(entry)

    def test_huge_lineno_falls_back(self):
        # lineno past i64: OverflowError at the binding boundary, so the
        # pure-Python fallback formats the message.
        entry = make_transcript_entry()
        self.assertParity(entry, lineno=2**70)

    def test_bool_lineno_falls_back(self):
        # A bool lineno is not an int lineno: the binding raises
        # TypeError so the reference formats the message.
        entry = make_transcript_entry()
        self.assertParity(entry, lineno=True)

    def test_rejections(self):
        base = make_transcript_entry()
        cases = [
            ("not an object", [1, 2]),
            ("not an object", "x"),
            ("missing field", {k: v for k, v in base.items() if k != "seed"}),
            ("bad variant", make_transcript_entry(variant="evil")),
            ("bad variant", make_transcript_entry(variant=None)),
            ("bool int", make_transcript_entry(seed=True)),
            ("float int", make_transcript_entry(seed=1.5)),
            ("str int", make_transcript_entry(dispatch_limit="4")),
            ("bad kind", make_transcript_entry(response={"kind": "weird"})),
            ("kind not dict", make_transcript_entry(response="x")),
            ("output not object", make_transcript_entry(
                response={"kind": "output", "output": [1]})),
            ("provider empty", make_transcript_entry(provider={})),
            ("provider blank name", make_transcript_entry(
                provider={"adapter_name": ""})),
            ("provider not dict", make_transcript_entry(provider="x")),
        ]
        for name, entry in cases:
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    validate_transcript_entry_py(entry, 3)
                self.assertParity(entry, 3)

    def test_error_kind_needs_no_output(self):
        entry = make_transcript_entry(response={"kind": "error", "detail": "x"})
        self.assertParity(entry)

    def test_line_number_in_message(self):
        entry = {"variant": "evil"}
        for fn in (validate_transcript_entry, validate_transcript_entry_py):
            try:
                fn(entry, 42)
            except ValueError as e:
                self.assertIn("transcript line 42", str(e))
            else:
                self.fail("expected ValueError")

    def test_randomized(self):
        rng = random.Random(20260927)
        for trial in range(300):
            entry = make_transcript_entry()
            r = rng.random()
            if r < 0.15:
                entry.pop(rng.choice(list(entry)))
            elif r < 0.3:
                entry["variant"] = rng.choice(["evil", None, 1, "BENIGN"])
            elif r < 0.45:
                entry[rng.choice(
                    ["dispatch_index", "seed", "dispatch_limit", "max_concurrency"]
                )] = rng.choice([True, 1.5, "4", None, -3])
            elif r < 0.6:
                entry["response"] = rng.choice(
                    [{"kind": "weird"}, "x", {"kind": "output"}, {"kind": "error"}]
                )
            elif r < 0.7:
                entry["provider"] = rng.choice(
                    [{}, {"adapter_name": ""}, "x", {"adapter_name": "ok"}]
                )
            self.assertParity(entry, rng.randint(1, 999))


class CostUsdParity(unittest.TestCase):
    TABLE = {
        "models": {
            "cheap": {"usd_per_1m_in": 0.10, "usd_per_1m_out": 0.50},
            "free": {"usd_per_1m_in": 0.0, "usd_per_1m_out": 0.0},
            "int-rates": {"usd_per_1m_in": 1, "usd_per_1m_out": 2},
            "str-rates": {"usd_per_1m_in": "0.10", "usd_per_1m_out": "0.50"},
        }
    }

    def test_known_vector(self):
        # 1M in @ $0.10 + 2M out @ $0.50 = $1.10, hand-computed.
        self.assertAlmostEqual(
            cost_usd("cheap", 1_000_000, 2_000_000, self.TABLE), 1.10, places=12
        )
        self.assertAlmostEqual(
            cost_usd_py("cheap", 1_000_000, 2_000_000, self.TABLE), 1.10, places=12
        )

    def test_unknown_model_zero(self):
        self.assertEqual(cost_usd("nope", 100, 100, self.TABLE), 0.0)

    def test_zero_tokens(self):
        self.assertEqual(cost_usd("cheap", 0, 0, self.TABLE), 0.0)

    def test_negative_rejected(self):
        for fn in (cost_usd, cost_usd_py):
            with self.assertRaises(ValueError):
                fn("cheap", -1, 0, self.TABLE)
            with self.assertRaises(ValueError):
                fn("cheap", 0, -5, self.TABLE)

    def test_huge_tokens_fall_back(self):
        # Token counts past i64: OverflowError at the binding boundary
        # (not TypeError), so the pure-Python fallback prices them.
        for tokens_in, tokens_out in ((2**70, 0), (0, 2**70), (2**70, 2**70)):
            self.assertEqual(
                cost_usd("cheap", tokens_in, tokens_out, self.TABLE),
                cost_usd_py("cheap", tokens_in, tokens_out, self.TABLE),
            )

    def test_bool_tokens_fall_back(self):
        # Bool token counts are not int token counts: the binding
        # raises TypeError so the reference prices them.
        for tokens_in, tokens_out in ((True, 0), (0, False), (True, True)):
            self.assertEqual(
                cost_usd("cheap", tokens_in, tokens_out, self.TABLE),
                cost_usd_py("cheap", tokens_in, tokens_out, self.TABLE),
            )

    def test_rate_shapes(self):
        # int rates and numeric-string rates behave like Python's float().
        self.assertAlmostEqual(cost_usd("int-rates", 1_000_000, 0, self.TABLE), 1.0)
        self.assertAlmostEqual(cost_usd("str-rates", 1_000_000, 0, self.TABLE), 0.10)

    def test_corrupt_table(self):
        # Missing "models" section or rate entry: KeyError, both backends.
        for table in ({}, {"models": {"cheap": {}}}):
            for fn in (cost_usd, cost_usd_py):
                with self.assertRaises((KeyError, TypeError, ValueError)):
                    fn("cheap", 1, 1, table)
        # Empty models section with an unknown model is not corrupt:
        # the model is simply unlisted -> 0.0.
        self.assertEqual(cost_usd("cheap", 1, 1, {"models": {}}), 0.0)
        self.assertEqual(cost_usd_py("cheap", 1, 1, {"models": {}}), 0.0)

    def test_randomized(self):
        rng = random.Random(20260927)
        models = list(self.TABLE["models"]) + ["unknown-model"]
        for trial in range(300):
            model = rng.choice(models)
            ti = rng.randint(0, 5_000_000)
            to = rng.randint(0, 5_000_000)
            table = (
                self.TABLE
                if rng.random() < 0.9
                else {"models": {model: {"usd_per_1m_in": rng.uniform(0, 5),
                                         "usd_per_1m_out": rng.uniform(0, 5)}}}
            )
            try:
                want = cost_usd_py(model, ti, to, table)
                want_exc = None
            except Exception as e:  # noqa: BLE001
                want_exc = e
            try:
                got = cost_usd(model, ti, to, table)
                got_exc = None
            except Exception as e:  # noqa: BLE001
                got_exc = e
            if want_exc is not None or got_exc is not None:
                self.assertEqual(type(want_exc), type(got_exc), f"trial {trial}")
            else:
                self.assertAlmostEqual(got, want, places=12, msg=f"trial {trial}")


class FingerprintEnvParity(unittest.TestCase):
    def test_known_vectors(self):
        vectors = [
            ({}, "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"),
            (
                {"b": 1, "a": [1, 2]},
                "94a786c3662bc7beeb598efa7d8cb58d7bea25d6c275ea9785a0230ff1f8c2ba",
            ),
            (
                {"os": "linux", "python": "3.12.1",
                 "torch": {"cuda": None, "version": "2.5.0"}},
                "a097b51384cd9989694a0cfc5fe800b214e943ff830f086be995ba9fbd727904",
            ),
        ]
        for env, expected in vectors:
            # Independent check straight from hashlib/json.
            canonical = json.dumps(env, sort_keys=True, separators=(",", ":"))
            self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), expected)
            self.assertEqual(fingerprint_env(env), expected)
            self.assertEqual(fingerprint_env_py(env), expected)

    def test_key_order_irrelevant(self):
        self.assertEqual(
            fingerprint_env({"b": 1, "a": [1, 2]}),
            fingerprint_env({"a": [1, 2], "b": 1}),
        )

    def test_unicode_nesting(self):
        env = {
            "s": "héllo→\U0001f600",
            "nest": {"a": [True, False, None, 1.5, {"deep": "x"}]},
            "empty": {},
        }
        self.assertEqual(fingerprint_env(env), fingerprint_env_py(env))

    def test_randomized(self):
        rng = random.Random(20260927)

        def rand_value(depth):
            if depth <= 0:
                return rng.choice([None, True, 1, 1.5, "x", "héllo"])
            return rng.choice([
                None, True, rng.randint(-99, 99), rng.uniform(-9, 9),
                "".join(rng.choice("ab→") for _ in range(rng.randint(0, 5))),
                [rand_value(depth - 1) for _ in range(rng.randint(0, 3))],
                {f"k{i}": rand_value(depth - 1) for i in range(rng.randint(0, 3))},
            ])

        for trial in range(200):
            env = {f"k{i}": rand_value(3) for i in range(rng.randint(0, 6))}
            self.assertEqual(
                fingerprint_env(env), fingerprint_env_py(env), f"trial {trial}"
            )


class SummarizeBytesParity(unittest.TestCase):
    def test_valid_file(self):
        lines = [
            json.dumps(make_case(i, family=f, severity=s, primitive=p))
            for i, (f, s, p) in enumerate([
                ("state_poisoning", "critical", "choice"),
                ("criteria_smuggling", "high", "score"),
                ("state_poisoning", "low", "abstain"),
            ])
        ]
        data = ("\n".join(lines) + "\n").encode()
        got = _summarize_bytes("t.jsonl", data)
        want = _summarize_bytes_py("t.jsonl", data)
        self.assertEqual(got, want)
        self.assertEqual(got["kind"], "cases")
        self.assertEqual(got["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(got["n_cases"], 3)
        self.assertEqual(
            got["n_by_family"], {"criteria_smuggling": 1, "state_poisoning": 2}
        )
        self.assertEqual(
            got["n_by_severity"], {"critical": 1, "high": 1, "low": 1}
        )
        self.assertEqual(
            got["n_by_primitive"], {"abstain": 1, "choice": 1, "score": 1}
        )
        # Maps are in sorted key order.
        self.assertEqual(
            list(got["n_by_family"]), sorted(got["n_by_family"])
        )

    def test_blank_lines_ignored(self):
        data = b"\n  \n" + json.dumps(make_case(0)).encode() + b"\n\n"
        got = _summarize_bytes("t.jsonl", data)
        self.assertEqual(got["n_cases"], 1)

    def test_invalid_json_error_parity(self):
        data = b'{"a": 1}\nnot json\n'
        with self.assertRaises(ValueError) as c1:
            _summarize_bytes("b.jsonl", data)
        with self.assertRaises(ValueError) as c2:
            _summarize_bytes_py("b.jsonl", data)
        self.assertEqual(str(c1.exception), str(c2.exception))

    def test_invalid_utf8_error_parity(self):
        for data in (b"\xff\xfe", b'{"a": "\xff"}'):
            with self.assertRaises(ValueError) as c1:
                _summarize_bytes("u.jsonl", data)
            with self.assertRaises(ValueError) as c2:
                _summarize_bytes_py("u.jsonl", data)
            self.assertEqual(str(c1.exception), str(c2.exception))

    def test_schema_errors_aggregated_in_line_order(self):
        lines = [
            json.dumps({"case_id": "bad-1"}),  # schema violation, line 1
            "not json",  # invalid JSON, line 2
            json.dumps(make_case(0)),  # valid, line 3
            json.dumps({"case_id": "bad-2", "family": "nope"}),  # line 4
        ]
        data = ("\n".join(lines) + "\n").encode()
        with self.assertRaises(ValueError) as c1:
            _summarize_bytes("s.jsonl", data)
        with self.assertRaises(ValueError) as c2:
            _summarize_bytes_py("s.jsonl", data)
        self.assertEqual(str(c1.exception), str(c2.exception))
        # Line order preserved: line 1 < line 2 < line 4.
        msg = str(c1.exception)
        self.assertLess(msg.index(":1:"), msg.index(":2:"))
        self.assertLess(msg.index(":2:"), msg.index(":4:"))

    def test_randomized(self):
        rng = random.Random(20260927)
        for trial in range(100):
            n = rng.randint(0, 12)
            lines = []
            for i in range(n):
                r = rng.random()
                if r < 0.7:
                    lines.append(json.dumps(make_case(
                        i,
                        family=rng.choice(FAMILIES),
                        severity=rng.choice(SEVERITIES),
                        primitive=rng.choice(PRIMITIVES),
                    )))
                elif r < 0.8:
                    lines.append("")  # blank
                elif r < 0.9:
                    lines.append("{invalid json")
                else:
                    lines.append(json.dumps({"case_id": f"bad-{i}"}))
            data = ("\n".join(lines) + "\n").encode()
            try:
                want = _summarize_bytes_py("t.jsonl", data)
                want_exc = None
            except Exception as e:  # noqa: BLE001
                want, want_exc = None, e
            try:
                got = _summarize_bytes("t.jsonl", data)
                got_exc = None
            except Exception as e:  # noqa: BLE001
                got, got_exc = None, e
            if want_exc is not None or got_exc is not None:
                self.assertIsNotNone(want_exc, f"trial {trial}")
                self.assertIsNotNone(got_exc, f"trial {trial}")
                self.assertEqual(type(want_exc), type(got_exc), f"trial {trial}")
                self.assertEqual(str(want_exc), str(got_exc), f"trial {trial}")
            else:
                self.assertEqual(got, want, f"trial {trial}")


    def test_unicode_line_boundaries(self):
        # Python's str.splitlines() splits on a wider boundary set than
        # Rust's str::lines (\x0b \x0c \x1c-\x1e \x85 \u2028 \u2029, plus
        # lone \r). These are legal unescaped inside JSON strings, so a
        # boundary inside a string value splits one valid line into two
        # invalid fragments for the reference.
        base = json.dumps(make_case(0))
        for boundary, name in [
            ("\u2028", "U+2028"),
            ("\u2029", "U+2029"),
            ("\u0085", "U+0085"),
            ("\x0b", "VT"),
            ("\x0c", "FF"),
            ("\x1c", "FS"),
            ("\x1d", "GS"),
            ("\x1e", "RS"),
            ("\r", "CR"),
        ]:
            line = base.replace("t-0000", f"t-0000{boundary}tail")
            data = (line + "\n").encode("utf-8")
            with self.assertRaises(ValueError, msg=name):
                _summarize_bytes_py("u.jsonl", data)
            # The dispatcher must agree exactly (before the fix the Rust
            # core saw one valid line and returned success here).
            with self.assertRaises(ValueError, msg=name) as c1:
                _summarize_bytes("u.jsonl", data)
            with self.assertRaises(ValueError, msg=name) as c2:
                _summarize_bytes_py("u.jsonl", data)
            self.assertEqual(str(c1.exception), str(c2.exception), name)

    def test_unicode_boundaries_as_separators(self):
        # The same characters as line separators: both backends must
        # count the same cases.
        lines = [json.dumps(make_case(i)) for i in range(3)]
        for boundary, name in [
            ("\u2028", "U+2028"),
            ("\u2029", "U+2029"),
            ("\r", "CR"),
            ("\x0b", "VT"),
        ]:
            data = (boundary.join(lines) + "\n").encode("utf-8")
            got = _summarize_bytes("u.jsonl", data)
            want = _summarize_bytes_py("u.jsonl", data)
            self.assertEqual(got, want, name)
            self.assertEqual(got["n_cases"], 3, name)

    def test_python_blank_line_detection(self):
        # A line of only \x1c is blank to Python's str.strip() (Rust's
        # str::trim misses \x1c-\x1f), so it must be skipped, not parsed.
        data = (
            json.dumps(make_case(0)) + "\n\x1c\n" + json.dumps(make_case(1)) + "\n"
        ).encode("utf-8")
        got = _summarize_bytes("u.jsonl", data)
        want = _summarize_bytes_py("u.jsonl", data)
        self.assertEqual(got, want)
        self.assertEqual(got["n_cases"], 2)


@unittest.skipUnless(_rust.RUST_AVAILABLE, "peira._core not built")
class RustBoundaryTypes(unittest.TestCase):
    """Exception types raised by the extension itself (not the fallback)."""

    def test_missing_key_is_keyerror(self):
        # The binding maps core "missing key" errors to KeyError, matching
        # the reference's dict subscription — no fallback involved.
        with self.assertRaises(KeyError):
            _rust._impl.records_record_from_transcript_entry({})
        with self.assertRaises(KeyError):
            _rust._impl.records_output_from_dict("score", {"decision": "x"})

    def test_validation_errors_are_valueerror(self):
        with self.assertRaises(ValueError):
            _rust._impl.records_validate_transcript_entry({"a": 1}, 1)
        with self.assertRaises(ValueError):
            _rust._impl.pricing_cost_usd("m", -1, 0, {"models": {}})

    def test_missing_attr_is_attributeerror(self):
        with self.assertRaises(AttributeError):
            _rust._impl.records_output_to_dict("choice", object())

    def test_non_json_values_rejected(self):
        with self.assertRaises(TypeError):
            _rust._impl.env_fingerprint_env({1: "non-string key"})
        with self.assertRaises(ValueError):
            _rust._impl.env_fingerprint_env({"f": float("nan")})

    def test_binding_overflow_is_overflowerror(self):
        # PyO3 raises OverflowError (not TypeError) when a Python int
        # exceeds i64 at a typed-argument binding boundary.
        with self.assertRaises(OverflowError):
            _rust._impl.records_blank_record(2**70, 0, 1)
        with self.assertRaises(OverflowError):
            _rust._impl.pricing_cost_usd(
                "cheap", 2**70, 0, {"models": {"cheap": {}}}
            )

    def test_non_mapping_response_is_typeerror(self):
        entry = {
            "seed": 7,
            "dispatch_index": 3,
            "dispatch_limit": 4,
            "response": "not-a-mapping",
        }
        with self.assertRaises(TypeError):
            _rust._impl.records_record_from_transcript_entry(entry)

    def test_non_object_output_is_attributeerror(self):
        entry = {
            "seed": 7,
            "dispatch_index": 3,
            "dispatch_limit": 4,
            "response": {"kind": "output", "output": [1, 2]},
        }
        with self.assertRaises(AttributeError):
            _rust._impl.records_record_from_transcript_entry(entry)

    def test_non_mapping_entry_exact_cpython_messages(self):
        # The binding mirrors CPython's exact subscript TypeError
        # messages per type: bytearray/range have their own messages
        # (not bytes'), and array/memoryview have bespoke ones.
        import array

        cases = [
            (
                bytearray(b"z"),
                "bytearray indices must be integers or slices, not str",
            ),
            (range(3), "range indices must be integers or slices, not str"),
            (array.array("i", [1]), "array indices must be integers"),
            (memoryview(b"z"), "memoryview: invalid slice key"),
            (b"z", "byte indices must be integers or slices, not str"),
        ]
        for bad, want in cases:
            with self.assertRaises(TypeError) as c:
                _rust._impl.records_record_from_transcript_entry(bad)
            self.assertEqual(str(c.exception), want, repr(bad))

    def test_dict_usage_is_typeerror(self):
        out = dataclasses.replace(
            ChoiceOutput(decision="deny", confidence=0.4, usage=None),
            usage={"model": "m"},
        )
        with self.assertRaises(TypeError):
            _rust._impl.records_output_to_dict("choice", out)

    def test_duck_typed_usage_is_typeerror(self):
        # Extension-direct: a non-dataclass usage is TypeError at the
        # boundary (the dispatcher falls back to the reference).

        class DuckUsage:
            model = "m"
            tokens_in = 1
            tokens_out = 2
            latency_ms = 1.0
            cost_usd = 0.0

        out = dataclasses.replace(
            ChoiceOutput(decision="approve", confidence=0.5, usage=None),
            usage=DuckUsage(),
        )
        with self.assertRaises(TypeError):
            _rust._impl.records_output_to_dict("choice", out)

    def test_nonfinite_usage_float_is_valueerror(self):
        # Extension-direct: nan/inf latency_ms or cost_usd is ValueError
        # at the boundary (the dispatcher falls back to the reference),
        # never a silent null.
        for field in ("latency_ms", "cost_usd"):
            for value in (float("nan"), float("inf"), float("-inf")):
                kw = dict(
                    model="m", tokens_in=1, tokens_out=2,
                    latency_ms=1.0, cost_usd=0.0,
                )
                kw[field] = value
                out = ChoiceOutput(
                    decision="approve", confidence=0.5,
                    usage=CallUsage(**kw),
                )
                with self.assertRaises(ValueError) as c:
                    _rust._impl.records_output_to_dict("choice", out)
                self.assertEqual(
                    str(c.exception), f"{field} must be a finite float"
                )

    def test_explicit_null_optionals_roundtrip(self):
        # Missing keys serialize absent; explicit nulls serialize null.
        d = _rust._impl.records_output_from_dict(
            "choice",
            {"decision": "approve", "abstained": None, "refusal_reason": None},
        )
        self.assertIsNone(d["abstained"])
        self.assertIsNone(d["refusal_reason"])
        d2 = _rust._impl.records_output_from_dict(
            "choice", {"decision": "approve"}
        )
        self.assertNotIn("abstained", d2)
        self.assertNotIn("refusal_reason", d2)

    def test_non_dict_entry_is_typeerror(self):
        # Extension-direct: exact CPython subscript messages.
        for bad, msg in [
            ([1, 2], "list indices must be integers or slices, not str"),
            ((1, 2), "tuple indices must be integers or slices, not str"),
            (None, "'NoneType' object is not subscriptable"),
            ("x", "string indices must be integers, not 'str'"),
            (42, "'int' object is not subscriptable"),
        ]:
            with self.assertRaises(TypeError) as c:
                _rust._impl.records_record_from_transcript_entry(bad)
            self.assertEqual(str(c.exception), msg, f"{bad!r}")

    def test_non_dict_output_from_dict_is_attributeerror(self):
        # Extension-direct: exact CPython attribute messages.
        for bad in ([1, 2], None, "x", 42):
            with self.assertRaises(AttributeError) as c:
                _rust._impl.records_output_from_dict("choice", bad)
            self.assertEqual(
                str(c.exception),
                f"'{type(bad).__name__}' object has no attribute 'get'",
                f"{bad!r}",
            )

    def test_bool_int_params_rejected(self):
        # Extension-direct: bool is rejected (not coerced) at every
        # lane-4 integer parameter, so the dispatcher falls back.
        with self.assertRaises(TypeError):
            _rust._impl.records_blank_record(True, 0, 1)
        with self.assertRaises(TypeError):
            _rust._impl.records_blank_record(7, False, 1)
        with self.assertRaises(TypeError):
            _rust._impl.records_validate_transcript_entry(
                make_transcript_entry(), True
            )
        with self.assertRaises(TypeError):
            _rust._impl.pricing_cost_usd("cheap", True, 0, {"models": {}})
        with self.assertRaises(TypeError):
            _rust._impl.pricing_cost_usd("cheap", 0, False, {"models": {}})
        with self.assertRaises(TypeError):
            _rust._impl.artifact_lock_payload(
                "v",
                "1.0",
                "abc",
                "dummy",
                "0",
                "trial-demo",
                {},
                [],
                "s",
                "2026-01-01",
                True,
                8,
                {},
                "def",
            )

    def test_summarize_unicode_boundaries(self):
        # Extension-direct: U+2028 as a separator counts two cases...
        lines = [json.dumps(make_case(i)) for i in range(2)]
        data = ("\u2028".join(lines) + "\n").encode("utf-8")
        got = _rust._impl.dataset_summarize_case_bytes("u.jsonl", data)
        self.assertEqual(got["n_cases"], 2)
        # ...a \x1c-only line is blank (Python strip semantics)...
        data = (
            json.dumps(make_case(0)) + "\n\x1c\n" + json.dumps(make_case(1)) + "\n"
        ).encode("utf-8")
        got = _rust._impl.dataset_summarize_case_bytes("u.jsonl", data)
        self.assertEqual(got["n_cases"], 2)
        # ...and U+2028 inside a JSON string is a ValueError, not a
        # silently accepted single line.
        line = json.dumps(make_case(0)).replace("t-0000", "t-0000\u2028tail")
        with self.assertRaises(ValueError):
            _rust._impl.dataset_summarize_case_bytes(
                "u.jsonl", (line + "\n").encode("utf-8")
            )


if __name__ == "__main__":
    unittest.main()
