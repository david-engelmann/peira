"""Tests for the environment fingerprint module (Layer 1b)."""

import hashlib
import json
import unittest

from peira.env_fingerprint import (
    collect_env,
    fingerprint_env,
    collect_and_fingerprint,
)


class TestCollectEnv(unittest.TestCase):
    def test_collect_env_has_required_keys(self):
        env = collect_env()
        for key in (
            "python", "python_implementation", "peira", "rust_backend",
            "torch", "transformers", "numpy", "os", "architecture",
        ):
            self.assertIn(key, env, f"missing key: {key}")

    def test_collect_env_is_json_serializable(self):
        env = collect_env()
        # Must not raise
        json.dumps(env)

    def test_torch_info_structure(self):
        env = collect_env()
        torch_info = env["torch"]
        self.assertIn("version", torch_info)
        self.assertIn("cuda", torch_info)

    def test_peira_info_structure(self):
        env = collect_env()
        peira_info = env["peira"]
        self.assertIn("version", peira_info)
        self.assertIn("editable", peira_info)

    def test_rust_backend_info_structure(self):
        env = collect_env()
        rust_info = env["rust_backend"]
        self.assertIn("available", rust_info)
        self.assertIsInstance(rust_info["available"], bool)


class TestFingerprint(unittest.TestCase):
    def test_fingerprint_is_stable(self):
        env = collect_env()
        fp1 = fingerprint_env(env)
        fp2 = fingerprint_env(env)
        self.assertEqual(fp1, fp2)

    def test_fingerprint_is_sha256_hex(self):
        fp = fingerprint_env(collect_env())
        # 64 hex chars
        self.assertEqual(len(fp), 64)
        int(fp, 16)  # must parse as hex

    def test_fingerprint_changes_with_env(self):
        env1 = {"a": 1, "b": 2}
        env2 = {"a": 1, "b": 3}
        self.assertNotEqual(fingerprint_env(env1), fingerprint_env(env2))

    def test_fingerprint_uses_canonical_json(self):
        # Key order should not affect the fingerprint
        env1 = {"a": 1, "b": 2}
        env2 = {"b": 2, "a": 1}
        self.assertEqual(fingerprint_env(env1), fingerprint_env(env2))

    def test_fingerprint_matches_manual_sha256(self):
        env = {"x": "test"}
        canonical = json.dumps(env, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.assertEqual(fingerprint_env(env), expected)


class TestCollectAndFingerprint(unittest.TestCase):
    def test_returns_tuple(self):
        env, fp = collect_and_fingerprint()
        self.assertIsInstance(env, dict)
        self.assertIsInstance(fp, str)
        self.assertEqual(fp, fingerprint_env(env))


class TestRustBackendInfo(unittest.TestCase):
    def test_matches_actual_availability(self):
        # The fingerprint must reflect reality: if the Rust extension is
        # importable, available must be True. The old code called
        # _rust.available() which doesn't exist, silently reporting False.
        from peira.env_fingerprint import _rust_backend_info
        info = _rust_backend_info()
        try:
            from peira._rust import _impl
            expected = _impl is not None
        except ImportError:
            expected = False
        self.assertEqual(info["available"], expected)
        if expected:
            self.assertIsNotNone(info["version"])


if __name__ == "__main__":
    unittest.main()


class TestPerfState(unittest.TestCase):
    def test_collect_env_has_perf_state(self):
        env = collect_env()
        self.assertIn("perf_state", env)
        ps = env["perf_state"]
        for key in ("cpu_governor", "boost_state", "affinity", "smt",
                    "observed_mhz"):
            self.assertIn(key, ps, f"missing perf_state key: {key}")

    def test_perf_state_value_types(self):
        from peira.env_fingerprint import collect_perf_state
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ps = collect_perf_state()
        if ps["cpu_governor"] is not None:
            self.assertIsInstance(ps["cpu_governor"], str)
        if ps["boost_state"] is not None:
            self.assertIn(ps["boost_state"], ("on", "off"))
        if ps["affinity"] is not None:
            self.assertIsInstance(ps["affinity"], list)
            self.assertTrue(all(isinstance(c, int) for c in ps["affinity"]))
        if ps["smt"] is not None:
            self.assertIsInstance(ps["smt"], bool)
        if ps["observed_mhz"] is not None:
            self.assertIsInstance(ps["observed_mhz"], float)
            self.assertGreater(ps["observed_mhz"], 0)

    def test_perf_state_warns_never_fails(self):
        import peira.env_fingerprint as ef
        real_read = ef._read_sysfs
        real_affinity = getattr(__import__("os"), "sched_affinity", None)

        # _read_sysfs contract: unreadable -> None.
        ef._read_sysfs = lambda path: None
        import os as _os
        had = hasattr(_os, "sched_affinity")
        if had:
            # Delete the attribute to force the AttributeError path in
            # _affinity(): setting it to None would raise TypeError on
            # call instead, which _affinity() does not catch.
            del _os.sched_affinity
        try:
            with self.assertWarns(UserWarning):
                ps = ef.collect_perf_state()
        finally:
            ef._read_sysfs = real_read
            if had:
                _os.sched_affinity = real_affinity
        for key in ("cpu_governor", "boost_state", "affinity", "smt",
                    "observed_mhz"):
            self.assertIsNone(ps[key], f"{key} should be None, not raised")

    def test_perf_state_json_serializable(self):
        import json
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            json.dumps(collect_env())
