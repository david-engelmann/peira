"""Tests for peira.adapters.discovery (P-4 entry_points registry).

These tests exercise the real ``importlib.metadata`` machinery where
possible; registry-content cases use synthetic DiscoveryResults so
they do not depend on what is installed in the test environment.
"""

import unittest
import unittest.mock
from dataclasses import replace
from types import SimpleNamespace

from peira.adapters import discovery
from peira.adapters.discovery import (
    ADAPTER_NAME_RE,
    AdapterDiscoveryError,
    AdapterNameCollisionError,
    AdapterNameMismatchError,
    AdapterRegistration,
    DiscoveryResult,
    check_name_binding,
    resolve_spec,
)


def _reg(name, dist="peira-adapter-foo", version="1.0.0"):
    return AdapterRegistration(
        registry_id=name,
        value="some_pkg.mod:adapter",
        dist_name=dist,
        dist_version=version,
        first_party=False,
    )


class ResolveSpecTest(unittest.TestCase):
    def test_mock(self):
        r = resolve_spec("mock")
        self.assertEqual(r.kind, "mock")
        self.assertIsNone(r.registration)

    def test_dotted_path_with_dot(self):
        r = resolve_spec("examples.minimal_adapter")
        self.assertEqual(r.kind, "dotted")

    def test_dotted_path_with_colon(self):
        r = resolve_spec("pkg.mod:Cls")
        self.assertEqual(r.kind, "dotted")

    def test_unknown_registry_id_fails_closed(self):
        with self.assertRaises(AdapterDiscoveryError) as ctx:
            resolve_spec("no-such-adapter-xyz-123")
        self.assertIn("unknown adapter", str(ctx.exception))

    def test_registry_hit(self):
        reg = _reg("my-adapter")
        result = DiscoveryResult({"my-adapter": reg}, {}, [])
        r = resolve_spec("my-adapter", result)
        self.assertEqual(r.kind, "registry")
        self.assertEqual(r.registration, reg)

    def test_ambiguous_registry_id_fails_closed(self):
        regs = [_reg("dup", dist="a"), _reg("dup", dist="b")]
        result = DiscoveryResult({}, {"dup": regs}, [])
        with self.assertRaises(AdapterNameCollisionError) as ctx:
            resolve_spec("dup", result)
        self.assertIn("multiple distributions", str(ctx.exception))
        self.assertIn("a", str(ctx.exception))


class NameValidationTest(unittest.TestCase):
    def test_valid_names(self):
        for name in ("ab", "shieldstral", "openai-structured",
                     "llama-prompt-guard-2", "x_1", "a" * 64):
            with self.subTest(name=name):
                self.assertIsNone(discovery._validate_name(name))

    def test_invalid_names(self):
        for name in ("UPPER", "has.dot", "has space", "", "a" * 65,
                     "mock", "peira-evil", "-lead", "a"):
            with self.subTest(name=name):
                self.assertIsNotNone(discovery._validate_name(name))

    def test_regex_is_ascii_only(self):
        # Homoglyph / unicode names must not validate: the explicit
        # character ranges reject them.
        self.assertIsNotNone(discovery._validate_name("shïeldstral"))
        self.assertFalse(ADAPTER_NAME_RE.match("shïeldstral"))


class NameBindingTest(unittest.TestCase):
    def test_matching_name_passes(self):
        check_name_binding("my-adapter",
                           SimpleNamespace(name="my-adapter"))

    def test_mismatched_name_fails_closed(self):
        with self.assertRaises(AdapterNameMismatchError) as ctx:
            check_name_binding("shieldstral",
                               SimpleNamespace(name="evil"))
        self.assertIn("registry 'shieldstral' served 'evil'",
                      str(ctx.exception))

    def test_missing_name_attribute_fails(self):
        with self.assertRaises(AdapterNameMismatchError):
            check_name_binding("x", SimpleNamespace())


class LoadRegisteredTest(unittest.TestCase):
    def _fake_entry_points(self, name, value, loaded):
        from importlib import metadata as _md

        class FakeEP:
            def __init__(self):
                self.name = name
                self.value = value
                self.dist = None

            def load(self):
                return loaded

        real = _md.entry_points

        def fake(*args, **kwargs):
            if kwargs.get("group") == discovery.ENTRY_POINT_GROUP:
                return [FakeEP()]
            return real(*args, **kwargs)

        return unittest.mock.patch.object(_md, "entry_points", fake)

    def test_load_enforces_name_binding(self):
        # A class whose name disagrees with the registry id must fail
        # closed at load time, not be silently usable.
        class EvilAdapter:
            name = "shieldstral"

            def __init__(self):
                pass

        reg = AdapterRegistration(
            registry_id="totally-legit", value="x:y",
            dist_name="evil-dist", dist_version="9.9.9",
            first_party=False,
        )
        with self._fake_entry_points("totally-legit", "x:y", EvilAdapter):
            with self.assertRaises(AdapterNameMismatchError):
                discovery.load_registered(reg)

    def test_load_matching_name_succeeds(self):
        class GoodAdapter:
            name = "good-adapter"

            def __init__(self):
                self.ready = True

        reg = AdapterRegistration(
            registry_id="good-adapter", value="x:y",
            dist_name="good-dist", dist_version="1.0.0",
            first_party=False,
        )
        with self._fake_entry_points("good-adapter", "x:y", GoodAdapter):
            adapter = discovery.load_registered(reg)
        self.assertTrue(adapter.ready)
    def test_discover_does_not_raise(self):
        # Must never raise for arbitrary registry content; bad entries
        # become issues, never exceptions.
        result = discovery.discover()
        self.assertIsInstance(result.registrations, dict)
        self.assertIsInstance(result.issues, list)

    def test_discover_does_not_import_adapters(self):
        # Discovery reads metadata only. A module that raises on
        # import must still be discoverable without side effects.
        import sys
        before = set(sys.modules)
        discovery.discover()
        after = set(sys.modules)
        new_impl_modules = {
            m for m in after - before
            if m.startswith("peira.adapters.")
            and m not in ("peira.adapters.base", "peira.adapters.discovery")
        }
        self.assertEqual(new_impl_modules, set())


if __name__ == "__main__":
    unittest.main()
