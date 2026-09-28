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
        with self.assertRaises(TypeError):
            backoff_delay(True, random.Random(0))
        with self.assertRaises(ValueError):
            backoff_delay(-1, random.Random(0))


# -- Retro R1 regression tests (PR #107 retrospective review) -------------
#
# Each of these fails on the pre-fix code (verified via git stash) and
# passes after. They run identically with and without the extension,
# except the direct-binding depth probe, which needs the extension.


def _cache_kw(**over):
    kw = dict(adapter_name="m", adapter_version="1", cache_namespace="",
              primitive="p", variant="v", case_id="c",
              case_input={"a": 1}, manifest_sha256="h")
    kw.update(over)
    return kw


class CacheKeyDepthGuard(unittest.TestCase):
    """P0-1: cyclic/deeply-nested case_input must raise ValueError,
    not segfault the process (exit 139, uncatchable)."""

    def test_cyclic_input_raises(self):
        cyclic: dict = {}
        cyclic["self"] = cyclic
        with self.assertRaises(ValueError):
            cache_key(**_cache_kw(case_input=cyclic))

    def test_deeply_nested_input_raises(self):
        deep: dict = {}
        cur = deep
        for _ in range(300):
            nxt: dict = {}
            cur["n"] = nxt
            cur = nxt
        with self.assertRaises(ValueError):
            cache_key(**_cache_kw(case_input=deep))

    def test_shallow_input_still_works(self):
        self.assertEqual(
            cache_key(**_cache_kw(case_input={"a": [1, {"b": None}]})),
            cache_key_py(**_cache_kw(case_input={"a": [1, {"b": None}]})),
        )

    def test_binding_depth_guard_direct(self):
        # The Rust `value_from_py` guard itself, bypassing the Python
        # pre-check: a cyclic input must raise ValueError, not abort.
        from peira._rust import _impl
        if _impl is None:
            self.skipTest("Rust core not built")
        cyclic: dict = {}
        cyclic["self"] = cyclic
        with self.assertRaises(ValueError):
            _impl.execution_cache_key(
                "m", "1", "", "p", "v", "c", cyclic, "h")


class BackoffDelayOverflow(unittest.TestCase):
    """attempt >= 1024: the reference raises OverflowError
    (2.0**attempt overflows); the dispatch must match it."""

    def test_overflow_matches_reference(self):
        for attempt in (1024, 2000, 2**40):
            with self.subTest(attempt=attempt):
                with self.assertRaises(OverflowError):
                    backoff_delay(attempt, random.Random(0))
                with self.assertRaises(OverflowError):
                    _backoff_delay_py(attempt, random.Random(0))

    def test_boundary_attempt_still_works(self):
        a = backoff_delay(1023, random.Random(1))
        b = _backoff_delay_py(1023, random.Random(1))
        self.assertEqual(a, b)


class ClassifyExceptionGigantic(unittest.TestCase):
    """Gigantic ints: D-11 normalization must apply on both backends."""

    def _exc(self, **kw):
        return ProviderError("", **kw)

    def test_gigantic_retry_after(self):
        # Reference used to yield (True, True, 10**400); the Rust path
        # normalized it to None per D-11. Both must agree now.
        exc = self._exc(status_code=None, retry_after=10**400)
        self.assertEqual(classify_exception(exc), (False, False, None))
        self.assertEqual(_classify_exception_py(exc), (False, False, None))

    def test_gigantic_status_code(self):
        # Out of i64 range the Rust binding cannot extract the int;
        # the reference treats it as an unknown (non-retryable) status.
        for status in (10**400, -(10**400), 2**63, -(2**63) - 1):
            with self.subTest(status=status):
                exc = self._exc(status_code=status)
                self.assertEqual(
                    classify_exception(exc), (False, False, None))
                self.assertEqual(
                    _classify_exception_py(exc), (False, False, None))

    def test_i64_boundaries_still_classify(self):
        # In-range extremes still travel through both backends.
        for status in (2**63 - 1, -(2**63)):
            with self.subTest(status=status):
                exc = self._exc(status_code=status)
                self.assertEqual(classify_exception(exc),
                                 _classify_exception_py(exc))


class BigIntFormatting(unittest.TestCase):
    """Ints wider than i64 format via Python str() on both backends."""

    def test_retry_jitter_seed_bigint(self):
        for seed in (10**400, -(10**400), 2**100):
            with self.subTest(seed=seed):
                self.assertEqual(
                    retry_jitter_seed(seed, 0, 0),
                    f"{seed}:0:0",
                )
                self.assertEqual(
                    retry_jitter_seed(seed, 0, 0),
                    retry_jitter_seed_py(seed, 0, 0),
                )

    def test_pseudonymous_call_id_bigint(self):
        for seed in (10**400, -(10**400)):
            with self.subTest(seed=seed):
                self.assertEqual(
                    _pseudonymous_call_id("n", seed, 3),
                    _pseudonymous_call_id_py("n", seed, 3),
                )


class CacheKeyBigInt(unittest.TestCase):
    """Ints wider than u64: the dispatched cache_key raises ValueError
    on both backends; the raw cache_key_py reference still hashes."""

    def test_too_wide_int_raises(self):
        for big in (2**64, 10**400, -(2**63) - 1):
            with self.subTest(big=big):
                with self.assertRaises(ValueError):
                    cache_key(**_cache_kw(case_input={"a": big}))

    def test_u64_range_still_works(self):
        # 2**63 fits u64 but not i64: accepted, identical both backends.
        kw = _cache_kw(case_input={"a": 2**63})
        self.assertEqual(cache_key(**kw), cache_key_py(**kw))

    def test_reference_still_hashes(self):
        kw = _cache_kw(case_input={"a": 2**64})
        self.assertEqual(cache_key_py(**kw), cache_key_py(**kw))


# -- Retro R2 regression tests (red-team re-audit of ebad63d) ------------
#
# Negative-control accounting (verified against the pre-fix parent
# ebad63d): Rust-active, 15 subtests fail (7 cache-key params, 3
# score-pair decisions, 2 int-retry_after, 3 nonce rejections); no-Rust,
# 16 fail (7 cache-key params, 3 score-pair decisions, 3 overflow
# messages, 3 nonce rejections).
#
# Per-test pre-fix behavior is NOT "every test fails in both modes":
#   - fail pre-fix in both modes: test_surrogate_params_raise_value_error,
#     test_surrogate_decisions_raise_value_error, and
#     test_lone_surrogate_nonce_rejected (nonce: the parent raised
#     UnicodeEncodeError at position 1 on the Rust path and position 15
#     in the reference — now a uniform ValueError on both backends);
#   - fail pre-fix only in no-Rust: test_overflow_message_uniform
#     (the parent already raised the uniform message on the Rust path);
#   - fail pre-fix only in Rust-active: test_int_retry_after_preserved
#     (the dispatcher is the reference in no-Rust, so nothing diverges);
#   - pass pre-fix in both modes: they guard against over-rejection or
#     pin parity, not the bug — test_clean_params_still_hash,
#     test_surrogate_primitive_rejected_at_construction,
#     test_float_retry_after_unchanged, test_clean_nonce_parity.
# All pass after the fix, in both modes.


class CacheKeySurrogateParams(unittest.TestCase):
    """P1-1: lone surrogates in the 7 string params must raise ValueError
    identically on both backends; the raw reference still hashes."""

    def test_surrogate_params_raise_value_error(self):
        for param in ("adapter_name", "adapter_version", "cache_namespace",
                      "primitive", "variant", "case_id", "manifest_sha256"):
            with self.subTest(param=param):
                kw = _cache_kw(**{param: "a\ud800b"})
                with self.assertRaises(ValueError) as ctx:
                    cache_key(**kw)
                self.assertEqual(
                    str(ctx.exception),
                    "strings with lone surrogates have no JSON representation",
                )
                # The raw reference still hashes whatever json.dumps accepts.
                self.assertEqual(cache_key_py(**kw), cache_key_py(**kw))

    def test_clean_params_still_hash(self):
        kw = _cache_kw()
        self.assertEqual(cache_key(**kw), cache_key_py(**kw))


class ScorePairSurrogateDecisions(unittest.TestCase):
    """P1-2: lone surrogates in decision strings must raise ValueError
    identically on both backends."""

    def test_surrogate_decisions_raise_value_error(self):
        case = _case()
        for args in (
            (case, _rec(decision="\ud800"), _rec()),
            (case, _rec(), _rec(decision="\ud800")),
            (_case(expected="\ud800"), _rec(), _rec()),
        ):
            with self.subTest(args=args):
                with self.assertRaises(ValueError) as ctx:
                    _score_pair(*args)
                self.assertEqual(
                    str(ctx.exception),
                    "strings with lone surrogates have no JSON representation",
                )

    def test_surrogate_primitive_rejected_at_construction(self):
        # Case.__post_init__ rejects unknown primitives, so a surrogate
        # primitive can never reach the dispatcher via normal
        # construction; the dispatcher's primitive check is
        # defense-in-depth against exotic construction paths.
        with self.assertRaises(ValueError):
            _case(primitive="\ud800")


class BackoffDelayOverflowMessage(unittest.TestCase):
    """P2-1: the hoisted attempt>=1024 check raises a uniform message on
    both backends."""

    def test_overflow_message_uniform(self):
        for attempt in (1024, 2000, 2**40):
            with self.subTest(attempt=attempt):
                with self.assertRaises(OverflowError) as ctx:
                    backoff_delay(attempt, random.Random(0))
                self.assertEqual(
                    str(ctx.exception),
                    f"attempt too large for float exponent: {attempt}",
                )


class ClassifyExceptionIntRetryAfter(unittest.TestCase):
    """P3-3: an int retry_after must survive the Rust path as an int
    (the reference preserves it; the dispatcher used to float() it)."""

    def test_int_retry_after_preserved(self):
        for exc in (
            ProviderError("", status_code=None, retry_after=5),
            ProviderError("", status_code=429, retry_after=30),
        ):
            with self.subTest(exc=exc):
                got = classify_exception(exc)
                self.assertEqual(got, _classify_exception_py(exc))
                # Load-bearing: == would pass for 5 == 5.0; the type must
                # match the reference exactly.
                self.assertIs(type(got[2]), int)

    def test_float_retry_after_unchanged(self):
        got = classify_exception(
            ProviderError("", status_code=None, retry_after=5.0))
        self.assertEqual(got, (True, True, 5.0))
        self.assertIs(type(got[2]), float)


class PseudonymousCallIdNonceSurrogate(unittest.TestCase):
    """Red-team follow-up: a lone-surrogate run_nonce must raise the
    identical ValueError on both backends (the parent raised
    UnicodeEncodeError at position 1 on the Rust path and position 15
    in the reference)."""

    def test_lone_surrogate_nonce_rejected(self):
        for nonce in ("run-\ud800-1", "\ud800", "a\udcffb"):
            with self.subTest(nonce=nonce):
                with self.assertRaises(ValueError) as ctx:
                    _pseudonymous_call_id(nonce, 7, 42)
                self.assertEqual(
                    str(ctx.exception),
                    "strings with lone surrogates have no JSON representation",
                )

    def test_clean_nonce_parity(self):
        for nonce in ("run-1", "", "caf\u00e9 \U0001f600"):
            with self.subTest(nonce=nonce):
                self.assertEqual(
                    _pseudonymous_call_id(nonce, 7, 42),
                    _pseudonymous_call_id_py(nonce, 7, 42),
                )


if __name__ == "__main__":
    unittest.main()
