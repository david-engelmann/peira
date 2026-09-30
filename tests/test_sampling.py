"""R-04: effective sampling-config capture + fail-closed validation.

Covers :mod:`peira.sampling` (source resolution, the fail-closed
gate, the cache-namespace fragment), the per-call transcript
carriage, the CallRecord carriage, and the cache-key regression for
the lm-eval-harness #3881 class (the key must cover the *effective*
config, not just the adapter's declared namespace).
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from peira.adapters.mock import MockAdapter
from peira.concurrency import cache_key
from peira.metrics import PerCaseResult
from peira.runner import load_cases, run_suite
from peira.sampling import (
    SAMPLING_SOURCE_DECLARED,
    SAMPLING_SOURCE_INCAPABLE,
    SAMPLING_SOURCE_UNKNOWN,
    SAMPLING_SOURCES,
    SamplingConfigError,
    effective_sampling_config,
    sampling_cache_namespace,
    validate_sampling_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _demo_cases(n=4):
    return load_cases(REPO_ROOT / "dataset" / "trial-demo")[:n]


class _DeclaredAdapter:
    """Adapter declaring its wire config via a decode_params method."""

    name = "declared"
    version = "1"
    _supports_temperature = True
    _supports_seed = True

    def decode_params(self):
        return {"temperature": 0.2, "seed": 11, "max_tokens": 256}


class _PropertyAdapter:
    """decode_params as a property, like _StructuredLLMBase."""

    name = "property"
    version = "1"
    _supports_temperature = True

    @property
    def decode_params(self):
        return {"temperature": 0.0, "max_tokens": 512}


class EffectiveSamplingConfigTests(unittest.TestCase):
    def test_mock_is_unknown(self):
        cfg = effective_sampling_config(MockAdapter())
        self.assertEqual(cfg["sampling_source"], SAMPLING_SOURCE_UNKNOWN)
        self.assertIsNone(cfg["temperature"])
        self.assertIsNone(cfg["seed"])
        self.assertIsNone(cfg["max_tokens"])

    def test_declared_method(self):
        cfg = effective_sampling_config(_DeclaredAdapter())
        self.assertEqual(cfg["sampling_source"], SAMPLING_SOURCE_DECLARED)
        self.assertEqual(cfg["temperature"], 0.2)
        self.assertEqual(cfg["seed"], 11)
        self.assertEqual(cfg["max_tokens"], 256)

    def test_declared_property(self):
        cfg = effective_sampling_config(_PropertyAdapter())
        self.assertEqual(cfg["sampling_source"], SAMPLING_SOURCE_DECLARED)
        self.assertEqual(cfg["temperature"], 0.0)

    def test_json_string_decode_params(self):
        class J:
            name = "j"
            decode_params = json.dumps(
                {"temperature": 0.5, "seed": 3}
            )

        cfg = effective_sampling_config(J())
        self.assertEqual(cfg["sampling_source"], SAMPLING_SOURCE_DECLARED)
        self.assertEqual(cfg["temperature"], 0.5)
        self.assertEqual(cfg["seed"], 3)

    def test_garbage_decode_params_is_unknown_not_a_crash(self):
        class G:
            name = "g"
            decode_params = "not json{{"

        cfg = effective_sampling_config(G())
        self.assertEqual(cfg["sampling_source"], SAMPLING_SOURCE_UNKNOWN)

    def test_raising_decode_params_is_unknown_not_a_crash(self):
        class R:
            name = "r"

            def decode_params(self):
                raise RuntimeError("provider exploded")

        cfg = effective_sampling_config(R())
        self.assertEqual(cfg["sampling_source"], SAMPLING_SOURCE_UNKNOWN)

    def test_provider_incapable_source(self):
        class I:
            name = "i"
            _supports_temperature = False

        cfg = effective_sampling_config(I())
        self.assertEqual(cfg["sampling_source"], SAMPLING_SOURCE_INCAPABLE)
        self.assertIsNone(cfg["temperature"])

    def test_source_vocabulary_is_closed(self):
        self.assertEqual(
            SAMPLING_SOURCES,
            {
                SAMPLING_SOURCE_DECLARED,
                SAMPLING_SOURCE_INCAPABLE,
                SAMPLING_SOURCE_UNKNOWN,
            },
        )


class FailClosedTests(unittest.TestCase):
    def test_declared_and_set_passes(self):
        cfg = validate_sampling_config(_DeclaredAdapter())
        self.assertEqual(cfg["temperature"], 0.2)

    def test_temperature_declared_but_unset_raises(self):
        class T:
            name = "t"
            _supports_temperature = True

        with self.assertRaises(SamplingConfigError):
            validate_sampling_config(T())

    def test_temperature_declared_decode_params_missing_it_raises(self):
        class T:
            name = "t"
            _supports_temperature = True

            def decode_params(self):
                return {"seed": 5}  # temperature missing

        with self.assertRaises(SamplingConfigError):
            validate_sampling_config(T())

    def test_seed_declared_but_unset_raises(self):
        class S:
            name = "s"
            _supports_seed = True

            def decode_params(self):
                return {"temperature": 0.0}  # seed missing

        with self.assertRaises(SamplingConfigError):
            validate_sampling_config(S())

    def test_never_opted_in_is_left_alone(self):
        # No _supports_temperature attribute: backward compatibility,
        # no raise even though nothing is set.
        validate_sampling_config(MockAdapter())

    def test_provider_incapable_does_not_raise(self):
        class I:
            name = "i"
            _supports_temperature = False

        validate_sampling_config(I())

    def test_error_is_a_value_error(self):
        self.assertTrue(issubclass(SamplingConfigError, ValueError))


class SamplingCacheNamespaceTests(unittest.TestCase):
    def test_covers_effective_config(self):
        frag = sampling_cache_namespace(
            {
                "temperature": 0.2,
                "seed": 11,
                "max_tokens": 256,
                "sampling_source": SAMPLING_SOURCE_DECLARED,
            }
        )
        self.assertIn("temperature=0.2", frag)
        self.assertIn("seed=11", frag)
        self.assertIn("max_tokens=256", frag)
        # The source is trust metadata, not sampling input: it must not
        # be key material.
        self.assertNotIn("sampling_source", frag)

    def test_empty_when_nothing_set(self):
        self.assertEqual(
            sampling_cache_namespace(effective_sampling_config(MockAdapter())),
            "",
        )
        self.assertEqual(sampling_cache_namespace(None), "")
        self.assertEqual(sampling_cache_namespace({}), "")

    def test_partial_config(self):
        frag = sampling_cache_namespace({"temperature": 0.0})
        self.assertEqual(frag, "temperature=0.0")


class TranscriptCarriageTests(unittest.TestCase):
    def test_transcript_entries_carry_sampling_config(self):
        with TemporaryDirectory() as tmp:
            tpath = str(Path(tmp) / "t.jsonl")
            cases = _demo_cases(2)
            nonce = "sampling-transcript-nonce"
            run_suite(
                MockAdapter(
                    script=MockAdapter.script_for(
                        cases, seed=0, run_nonce=nonce
                    )
                ),
                cases,
                "trial-demo",
                "0.1.0-demo",
                seed=0,
                transcript_path=tpath,
                run_nonce=nonce,
            )
            entries = [
                json.loads(line)
                for line in open(tpath, encoding="utf-8")
            ]
        self.assertEqual(len(entries), 4)  # 2 cases x 2 variants
        for entry in entries:
            self.assertIn("sampling_config", entry)
            cfg = entry["sampling_config"]
            self.assertEqual(
                cfg["sampling_source"], SAMPLING_SOURCE_UNKNOWN
            )

    def test_call_records_carry_sampling_config(self):
        with TemporaryDirectory() as tmp:
            cases = _demo_cases(2)
            nonce = "sampling-record-nonce"
            artifact = run_suite(
                MockAdapter(
                    script=MockAdapter.script_for(
                        cases, seed=0, run_nonce=nonce
                    )
                ),
                cases,
                "trial-demo",
                "0.1.0-demo",
                seed=0,
                run_nonce=nonce,
            )
        results = [PerCaseResult.from_dict(r) for r in artifact.results]
        self.assertTrue(results)
        for r in results:
            for record in (r.benign, r.attacked):
                self.assertIsNotNone(record.sampling_config)
                self.assertEqual(
                    record.sampling_config["sampling_source"],
                    SAMPLING_SOURCE_UNKNOWN,
                )

    def test_fail_closed_inside_run_suite(self):
        class T(MockAdapter):
            name = "fail-closed-mock"
            _supports_temperature = True
            # No decode_params: temperature unset -> must fail closed.

        with TemporaryDirectory() as tmp:
            cases = _demo_cases(1)
            nonce = "sampling-failclosed-nonce"
            with self.assertRaises(SamplingConfigError):
                run_suite(
                    T(
                        script=MockAdapter.script_for(
                            cases, seed=0, run_nonce=nonce
                        )
                    ),
                    cases,
                    "trial-demo",
                    "0.1.0-demo",
                    seed=0,
                    run_nonce=nonce,
                )


class CacheKeyRegressionTests(unittest.TestCase):
    """lm-eval-harness #3881 class: the cache key must cover the
    effective sampling config, so a run at temperature 0.7 never
    reuses entries recorded at temperature 0.0."""

    def test_effective_config_changes_the_key(self):
        inp = {"prompt": "x"}
        base = dict(
            adapter_name="a",
            adapter_version="1",
            primitive="choice",
            variant="benign",
            case_id="c1",
            case_input=inp,
            manifest_sha256="m",
        )
        k_cold = cache_key(
            cache_namespace="ns|temperature=0.0", **base
        )
        k_hot = cache_key(
            cache_namespace="ns|temperature=0.7", **base
        )
        self.assertNotEqual(k_cold, k_hot)

    def test_same_effective_config_same_key(self):
        inp = {"prompt": "x"}
        base = dict(
            adapter_name="a",
            adapter_version="1",
            primitive="choice",
            variant="benign",
            case_id="c1",
            case_input=inp,
            manifest_sha256="m",
        )
        self.assertEqual(
            cache_key(cache_namespace="ns|temperature=0.0", **base),
            cache_key(cache_namespace="ns|temperature=0.0", **base),
        )

    def test_different_temperatures_do_not_share_cache_entries(self):
        # End to end: two runs of a temperature-capable adapter at
        # different temperatures over one shared cache dir must both
        # call the adapter (no silent cross-temperature reuse).
        from peira.adapters.base import ChoiceOutput

        class TempAdapter(MockAdapter):
            name = "temp-cache-test"
            _supports_temperature = True

            def __init__(self, temperature, **kw):
                super().__init__(**kw)
                self._temperature = temperature
                self.calls = 0

            @property
            def decode_params(self):
                return {"temperature": self._temperature}

            def decide(self, case_input, primitive, context=None):
                self.calls += 1
                return ChoiceOutput(decision="deny", confidence=0.9)

        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cases = _demo_cases(2)
            cold = TempAdapter(0.0)
            run_suite(cold, cases, "trial-demo", "0.1.0-demo", seed=0,
                      cache_dir=cache_dir)
            self.assertEqual(cold.calls, 4)  # 2 cases x 2 variants
            hot = TempAdapter(0.7)
            run_suite(hot, cases, "trial-demo", "0.1.0-demo", seed=0,
                      cache_dir=cache_dir)
            # A #3881-class bug would serve the hot run from the cold
            # run's cache entries: 0 calls. The fix forces 4 fresh
            # calls.
            self.assertEqual(hot.calls, 4)

    def test_unset_config_keeps_existing_cache_entries(self):
        # Adapters with no sampling knobs set produce an empty
        # fragment: their pre-R-04 cache entries keep working.
        from peira.adapters.mock import MockAdapter as M

        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cases = _demo_cases(2)
            nonce = "sampling-cache-compat-nonce"
            first = M(
                script=M.script_for(cases, seed=0, run_nonce=nonce)
            )
            run_suite(first, cases, "trial-demo", "0.1.0-demo", seed=0,
                      cache_dir=cache_dir, run_nonce=nonce)
            # Second run under a different nonce would miss on call id
            # anyway; the check that matters is the namespace fold is
            # empty for the mock, i.e. key-identical to pre-R-04.
            self.assertEqual(
                sampling_cache_namespace(
                    effective_sampling_config(M())
                ),
                "",
            )


if __name__ == "__main__":
    unittest.main()
