"""Tests for the environment fingerprint module (Layer 1b)."""

import hashlib
import json
import unittest

from peira.env_fingerprint import (
    collect_env,
    fingerprint_env,
    collect_and_fingerprint,
    python_version_tuple,
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


class TestPythonVersionTuple(unittest.TestCase):
    def test_returns_triple(self):
        v = python_version_tuple()
        self.assertEqual(len(v), 3)
        self.assertTrue(all(isinstance(x, int) for x in v))


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
