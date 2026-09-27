"""Backend parity for the execution-engine Rust ports (lane 3).

Covers `peira.runner` (`_pseudonymous_call_id`, `_score_pair`) and
`peira.concurrency` (`cache_key`, `retry_jitter_seed`,
`classify_exception`, `backoff_delay`).

These tests pass whether or not `peira._core` is built: they compare
the public dispatched functions against the `_xxx_py` reference
implementations. When the extension is present the public names run
the Rust core, so the same suite exercises both backends.
"""

import random
import string
import unittest

from peira import _rust
from peira.adapters.base import ProviderError
from peira.concurrency import (
    _backoff_delay_py,
    _classify_exception_py,
    backoff_delay,
    cache_key,
    cache_key_py,
    classify_exception,
    retry_jitter_seed,
    retry_jitter_seed_py,
)
from peira.metrics import CallRecord
from peira.runner import (
    _pseudonymous_call_id,
    _pseudonymous_call_id_py,
    _score_pair,
    _score_pair_py,
)
from peira.schema import AttackedVariant, BenignVariant, Case


def _rand_str(rng, n=8):
    return "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(n))


def _rec(**kw):
    base = dict(decision="approve", confidence=0.9, abstained=False,
                refusal_reason="", usage=None, seed=0, dispatch_index=0,
                malformed=False)
    base.update(kw)
    return CallRecord(**base)


def _case(primitive="choice", expected="approve"):
    return Case(
        case_id="c1", family="f", primitive=primitive, severity="high",
        benign=BenignVariant(input={}, expected_decision=expected),
        attacked=AttackedVariant(input={}, target_decision=None),
    )


def _jsonish(rng, depth=0):
    """Random JSON-shaped value, including unicode and edge floats."""
    if depth > 2:
        return rng.choice([None, True, 1, "x", "caf\u00e9 \U0001f600"])
    choice = rng.randrange(8)
    if choice == 0:
        return None
    if choice == 1:
        return rng.choice([True, False])
    if choice == 2:
        return rng.choice([0, -1, 2**63 - 1, -(2**63)])
    if choice == 3:
        return rng.choice([0.0, -0.0, 1.5, 1e300, 2.5e-7])
    if choice == 4:
        # No lone surrogates: Python's json.dumps escapes them, but
        # Rust strings cannot hold them — the Rust path fails loudly
        # on such inputs by design (tested below), so they are out of
        # scope for parity fuzzing.
        return "".join(rng.choice("a\u00e9\U0001f600") for _ in range(rng.randrange(6)))
    if choice == 5:
        return [_jsonish(rng, depth + 1) for _ in range(rng.randrange(4))]
    if choice == 6:
        return {_rand_str(rng, 3): _jsonish(rng, depth + 1)
                for _ in range(rng.randrange(4))}
    return _rand_str(rng)


class PseudonymousCallIdParity(unittest.TestCase):
    def test_known_vector(self):
        # CPython hashlib vector: sha256 of the literal format string.
        self.assertEqual(
            _pseudonymous_call_id_py("test-nonce", 7, 42),
            "call-d438306686915c7e",
        )
        self.assertEqual(
            _pseudonymous_call_id("test-nonce", 7, 42),
            "call-d438306686915c7e",
        )

    def test_randomized_parity(self):
        rng = random.Random(20260927)
        for _ in range(200):
            nonce = _rand_str(rng, rng.randrange(0, 32))
            seed = rng.choice([0, 1, 7, -3, 2**62])
            idx = rng.choice([0, 1, 41, 2**40])
            self.assertEqual(
                _pseudonymous_call_id(nonce, seed, idx),
                _pseudonymous_call_id_py(nonce, seed, idx),
            )

    def test_validation(self):
        # D-11: a bool seed would format as "True" in Python but 1 in
        # Rust — must fail loudly, not compute divergent ids.
        if _rust._impl is None:
            self.skipTest("Rust core not built")
        with self.assertRaises(TypeError):
            _pseudonymous_call_id("n", True, 0)
        with self.assertRaises(TypeError):
            _pseudonymous_call_id("n", 0, 0.0)
        with self.assertRaises(TypeError):
            _pseudonymous_call_id(b"n", 0, 0)


class ScorePairParity(unittest.TestCase):
    def _results(self, case, benign, attacked):
        a = _score_pair(case, benign, attacked)
        b = _score_pair_py(case, benign, attacked)
        return (a.flipped, a.eligible, a.ineligibility_reason), \
            (b.flipped, b.eligible, b.ineligibility_reason)

    def test_randomized_parity(self):
        rng = random.Random(20260927)
        decisions = ["approve", "deny", "", "Approve"]
        for _ in range(500):
            primitive = rng.choice(["choice", "score", "abstain"])
            expected = rng.choice(decisions)
            case = _case(primitive, expected)
            benign = _rec(
                decision=rng.choice(decisions),
                abstained=rng.random() < 0.3,
                malformed=rng.random() < 0.2,
            )
            attacked = _rec(
                decision=rng.choice(decisions),
                abstained=rng.random() < 0.3,
                malformed=rng.random() < 0.2,
            )
            a, b = self._results(case, benign, attacked)
            self.assertEqual(a, b)

    def test_validation(self):
        # D-11: mistyped record fields must fail loudly at dispatch.
        if _rust._impl is None:
            self.skipTest("Rust core not built")
        case = _case()
        benign = _rec(abstained=1)  # int, not bool
        with self.assertRaises(TypeError):
            _score_pair(case, benign, _rec())


class CacheKeyParity(unittest.TestCase):
    def test_known_vector(self):
        kw = dict(adapter_name="mock", adapter_version="1.0",
                  cache_namespace="", primitive="choice", variant="benign",
                  case_id="c1", case_input={"prompt": "hi"},
                  manifest_sha256="deadbeef")
        # CPython json.dumps + hashlib vector.
        self.assertEqual(
            cache_key_py(**kw),
            "60bc93ca125584ad3eadb2c0eefbf187fd855c07f3e7fae67acbb985d6c76a0f",
        )
        self.assertEqual(cache_key(**kw), cache_key_py(**kw))

    def test_randomized_parity(self):
        rng = random.Random(20260927)
        for _ in range(100):
            kw = dict(
                adapter_name=_rand_str(rng),
                adapter_version=_rand_str(rng, 4),
                cache_namespace=rng.choice(["", "ns", _rand_str(rng)]),
                primitive=rng.choice(["choice", "score", "abstain"]),
                variant=rng.choice(["benign", "attacked"]),
                case_id=_rand_str(rng),
                case_input={"input": _jsonish(rng)},
                manifest_sha256=_rand_str(rng, 16),
            )
            self.assertEqual(cache_key(**kw), cache_key_py(**kw))

    def test_validation(self):
        if _rust._impl is None:
            self.skipTest("Rust core not built")
        kw = dict(adapter_name="m", adapter_version="1", cache_namespace="",
                  primitive="p", variant="v", case_id="c",
                  case_input={"a": 1}, manifest_sha256="h")
        # Non-finite floats have no JSON representation: the Rust path
        # fails loudly rather than hashing a divergent key.
        bad = dict(kw, case_input={"a": float("nan")})
        with self.assertRaises((TypeError, ValueError)):
            cache_key(**bad)
        # Lone surrogates: Python's json.dumps escapes them, but Rust
        # strings cannot hold them — loud failure, not a divergent key.
        bad = dict(kw, case_input={"a": "\ud800"})
        with self.assertRaises((TypeError, ValueError)):
            cache_key(**bad)
        # But the reference implementation still handles them fine.
        self.assertEqual(cache_key_py(**bad), cache_key_py(**bad))
        bad = dict(kw, adapter_name=7)
        with self.assertRaises(TypeError):
            cache_key(**bad)


class RetryJitterSeedParity(unittest.TestCase):
    def test_randomized_parity(self):
        rng = random.Random(20260927)
        for _ in range(200):
            seed = rng.choice([None, 0, 7, -1, 2**40])
            idx = rng.choice([0, 1, 999])
            attempt = rng.choice([0, 1, 5])
            self.assertEqual(
                retry_jitter_seed(seed, idx, attempt),
                retry_jitter_seed_py(seed, idx, attempt),
            )

    def test_validation(self):
        if _rust._impl is None:
            self.skipTest("Rust core not built")
        with self.assertRaises(TypeError):
            retry_jitter_seed(True, 0, 0)


class ClassifyExceptionParity(unittest.TestCase):
    def _exc(self, status, retry_after):
        return ProviderError("", status_code=status, retry_after=retry_after)

    def test_randomized_parity(self):
        rng = random.Random(20260927)
        statuses = [None, 400, 401, 403, 404, 408, 409, 418, 422,
                    429, 500, 502, 503, 599]
        retry_afters = [None, 0.0, 1.5, 30, True, "5", float("nan"), -2.0]
        for _ in range(300):
            exc = self._exc(rng.choice(statuses), rng.choice(retry_afters))
            self.assertEqual(classify_exception(exc),
                             _classify_exception_py(exc))
        # Timeout / connection branches.
        for exc in (TimeoutError(), ConnectionError(), ValueError("x")):
            self.assertEqual(classify_exception(exc),
                             _classify_exception_py(exc))

    def test_congestion_signal_preserved(self):
        self.assertEqual(classify_exception(self._exc(429, None)),
                         (True, True, None))
        self.assertEqual(classify_exception(self._exc(None, 2.0)),
                         (True, True, 2.0))
        self.assertEqual(classify_exception(self._exc(400, 5.0)),
                         (False, False, None))


class BackoffDelayParity(unittest.TestCase):
    def test_randomized_parity(self):
        # Equal seeds => identical draws, so this also proves the Rust
        # bound is bit-identical to the Python bound for real attempts.
        rng = random.Random(20260927)
        for _ in range(100):
            attempt = rng.randrange(0, 9)
            base = rng.choice([0.5, 1.0, 2.0])
            cap = rng.choice([10.0, 60.0])
            s = rng.randrange(2**32)
            a = backoff_delay(attempt, random.Random(s), base, cap)
            b = _backoff_delay_py(attempt, random.Random(s), base, cap)
            self.assertEqual(a, b)
            self.assertLessEqual(a, cap)

    def test_validation(self):
        if _rust._impl is None:
            self.skipTest("Rust core not built")
        with self.assertRaises(TypeError):
            backoff_delay(True, random.Random(0))
        with self.assertRaises(ValueError):
            backoff_delay(-1, random.Random(0))


if __name__ == "__main__":
    unittest.main()
