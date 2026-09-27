"""Tests for peira.api_pins: pinned API model versions (Layer 3a).

No API calls, no network: the registry is the source of truth and the
provider SDKs are faked in sys.modules, following tests/test_llm_adapters.py.
"""

import inspect
import os
import sys
import unittest
from contextlib import contextmanager
from types import ModuleType
from unittest import mock

from peira import api_pins
from peira.adapters.llm import (
    AnthropicAdapter,
    GoogleAdapter,
    MoonshotAdapter,
    OpenAIAdapter,
)
from peira.api_pins import (
    DEPRECATED_PINS,
    PINNED_API_MODELS,
    DeprecatedPinError,
    UnknownAdapterPinError,
    get_pinned_model,
    is_pinned_model,
    pin_status,
    validate_registry,
)
from peira.doctor import SystemInfo, check_adapter


@contextmanager
def _env(**vars):
    """Temporarily set environment variables."""
    old = {k: os.environ.get(k) for k in vars}
    os.environ.update(vars)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _fake_openai_module():
    mod = ModuleType("openai")

    class _Client:
        def __init__(self, **kwargs):
            pass

    mod.OpenAI = _Client
    mod.APIStatusError = type("APIStatusError", (Exception,), {})
    mod.APITimeoutError = type("APITimeoutError", (Exception,), {})
    mod.APIConnectionError = type("APIConnectionError", (Exception,), {})
    return mod


@contextmanager
def _fake_modules(mods):
    old = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


# ---------------------------------------------------------------------------
# get_pinned_model: the pin lookup, fail closed.
# ---------------------------------------------------------------------------


class TestGetPinnedModel(unittest.TestCase):
    def test_all_four_adapters_have_pins(self):
        self.assertEqual(
            get_pinned_model("openai-structured"), "gpt-5.6-luna-2026-08-01")
        self.assertEqual(
            get_pinned_model("anthropic-structured"),
            "claude-sonnet-5-20260915")
        self.assertEqual(
            get_pinned_model("google-structured"), "gemini-3.8-flash-001")
        self.assertEqual(
            get_pinned_model("moonshot-structured"), "kimi-k3-2026-08-01")

    def test_unknown_adapter_fails_closed(self):
        # Never guesses: an unregistered adapter is a loud error, not a
        # silent alias.
        with self.assertRaises(UnknownAdapterPinError) as ctx:
            get_pinned_model("openai-future")
        self.assertIn("openai-future", str(ctx.exception))

    def test_unknown_adapter_names_known_adapters(self):
        with self.assertRaises(UnknownAdapterPinError) as ctx:
            get_pinned_model("nope")
        for name in PINNED_API_MODELS:
            self.assertIn(name, str(ctx.exception))

    def test_deprecated_pin_fails_closed_with_replacement(self):
        with mock.patch.dict(
            api_pins.DEPRECATED_PINS,
            {"gpt-5.6-luna-2026-05-01": "gpt-5.6-luna-2026-08-01"},
            clear=False,
        ), mock.patch.dict(
            api_pins.PINNED_API_MODELS,
            {"openai-structured": "gpt-5.6-luna-2026-05-01"},
            clear=False,
        ):
            with self.assertRaises(DeprecatedPinError) as ctx:
                get_pinned_model("openai-structured")
        self.assertIn("gpt-5.6-luna-2026-08-01", str(ctx.exception))

    def test_unversioned_pin_is_registry_corruption(self):
        with mock.patch.dict(
            api_pins.PINNED_API_MODELS,
            {"openai-structured": "gpt-5.6-luna"},
            clear=False,
        ):
            with self.assertRaises(ValueError):
                get_pinned_model("openai-structured")


# ---------------------------------------------------------------------------
# is_pinned_model / pin_status: classification helpers.
# ---------------------------------------------------------------------------


class TestIsPinnedModel(unittest.TestCase):
    def test_pins_are_pinned(self):
        for pin in PINNED_API_MODELS.values():
            self.assertTrue(is_pinned_model(pin), pin)

    def test_floating_aliases_are_not_pinned(self):
        for alias in (
            "gpt-5.6-luna", "claude-sonnet-5", "gemini-3.8-flash",
            "kimi-k3", "gpt-6", "latest", "",
        ):
            self.assertFalse(is_pinned_model(alias), alias)

    def test_non_strings_are_not_pinned(self):
        self.assertFalse(is_pinned_model(None))
        self.assertFalse(is_pinned_model(123))

    def test_deprecated_pin_is_not_current(self):
        with mock.patch.dict(
            api_pins.DEPRECATED_PINS,
            {"gpt-5.6-luna-2026-05-01": "gpt-5.6-luna-2026-08-01"},
            clear=False,
        ):
            self.assertFalse(is_pinned_model("gpt-5.6-luna-2026-05-01"))


class TestPinStatus(unittest.TestCase):
    def test_pinned(self):
        status, detail = pin_status(
            "openai-structured", "gpt-5.6-luna-2026-08-01")
        self.assertEqual(status, "pinned")
        self.assertIn("gpt-5.6-luna-2026-08-01", detail)

    def test_unpinned_alias(self):
        status, detail = pin_status("openai-structured", "gpt-5.6-luna")
        self.assertEqual(status, "unpinned")
        self.assertIn("gpt-5.6-luna-2026-08-01", detail)

    def test_deprecated(self):
        with mock.patch.dict(
            api_pins.DEPRECATED_PINS,
            {"gpt-5.6-luna-2026-05-01": "gpt-5.6-luna-2026-08-01"},
            clear=False,
        ):
            status, detail = pin_status(
                "openai-structured", "gpt-5.6-luna-2026-05-01")
        self.assertEqual(status, "deprecated")
        self.assertIn("gpt-5.6-luna-2026-08-01", detail)

    def test_unknown_adapter(self):
        status, _ = pin_status("nope", "gpt-5.6-luna-2026-08-01")
        self.assertEqual(status, "unknown_adapter")

    def test_never_raises_on_bad_input(self):
        for adapter, model in (
            ("openai-structured", None),
            ("openai-structured", 123),
            (None, None),
            ("", ""),
        ):
            status, detail = pin_status(adapter, model)
            self.assertIsInstance(status, str)
            self.assertIsInstance(detail, str)


class TestValidateRegistry(unittest.TestCase):
    def test_shipped_registry_is_valid(self):
        validate_registry()  # must not raise

    def test_unversioned_pin_rejected(self):
        with mock.patch.dict(
            api_pins.PINNED_API_MODELS,
            {"openai-structured": "gpt-5.6-luna"},
            clear=False,
        ):
            with self.assertRaises(ValueError):
                validate_registry()

    def test_deprecated_pin_rejected(self):
        with mock.patch.dict(
            api_pins.DEPRECATED_PINS,
            {"gpt-5.6-luna-2026-08-01": "gpt-5.6-luna-2026-09-01"},
            clear=False,
        ):
            with self.assertRaises(ValueError):
                validate_registry()


# ---------------------------------------------------------------------------
# Adapter integration: defaults are the pins; pins land in the artifact.
# ---------------------------------------------------------------------------


class TestAdapterDefaultsArePinned(unittest.TestCase):
    ADAPTERS = (
        OpenAIAdapter,
        AnthropicAdapter,
        GoogleAdapter,
        MoonshotAdapter,
    )

    def test_constructor_default_is_the_pin(self):
        for cls in self.ADAPTERS:
            with self.subTest(adapter=cls.name):
                default = inspect.signature(
                    cls.__init__).parameters["model"].default
                self.assertEqual(default, get_pinned_model(cls.name))
                self.assertTrue(is_pinned_model(default))

    def test_default_version_is_pinned(self):
        # adapter.version is what the runner seals as adapter_version in
        # the run artifact (part of the analysis lock).
        with _fake_modules({"openai": _fake_openai_module()}), \
                _env(OPENAI_API_KEY="sk-test"):
            adapter = OpenAIAdapter()
        self.assertEqual(
            adapter.version, get_pinned_model("openai-structured"))
        self.assertTrue(is_pinned_model(adapter.version))

    def test_explicit_deprecated_model_fails_closed(self):
        with mock.patch.dict(
            DEPRECATED_PINS,
            {"gpt-5.6-luna-2026-05-01": "gpt-5.6-luna-2026-08-01"},
            clear=False,
        ), _fake_modules({"openai": _fake_openai_module()}), \
                _env(OPENAI_API_KEY="sk-test"):
            with self.assertRaises(DeprecatedPinError) as ctx:
                OpenAIAdapter(model="gpt-5.6-luna-2026-05-01")
        self.assertIn("gpt-5.6-luna-2026-08-01", str(ctx.exception))

    def test_explicit_override_still_allowed(self):
        # Researchers may opt out of the pin explicitly; the version
        # string then honestly records the unpinned model.
        with _fake_modules({"openai": _fake_openai_module()}), \
                _env(OPENAI_API_KEY="sk-test"):
            adapter = OpenAIAdapter(model="gpt-5.6-luna")
        self.assertEqual(adapter.version, "gpt-5.6-luna")
        self.assertFalse(is_pinned_model(adapter.version))


# ---------------------------------------------------------------------------
# Doctor integration: warns on unpinned API adapter defaults.
# ---------------------------------------------------------------------------


def _make_adapter_class(name, default_model):
    class _FakeAPIAdapter:
        pass

    _FakeAPIAdapter.name = name
    _FakeAPIAdapter._env_vars = ("PEIRA_API_PINS_TEST_KEY",)

    def __init__(self, model=default_model):
        self.model = model

    _FakeAPIAdapter.__init__ = __init__
    _FakeAPIAdapter.decide = lambda self, *a: None
    return _FakeAPIAdapter


class TestDoctorPinWarnings(unittest.TestCase):
    def test_unpinned_default_warns(self):
        cls = _make_adapter_class("openai-structured", "gpt-5.6-luna")
        with _env(PEIRA_API_PINS_TEST_KEY="x"):
            result = check_adapter(cls, SystemInfo())
        self.assertEqual(result.status, "ready")
        self.assertIn("API model pin", result.detail)
        self.assertIn("gpt-5.6-luna-2026-08-01", result.detail)

    def test_pinned_default_no_warning(self):
        cls = _make_adapter_class(
            "openai-structured", "gpt-5.6-luna-2026-08-01")
        with _env(PEIRA_API_PINS_TEST_KEY="x"):
            result = check_adapter(cls, SystemInfo())
        self.assertEqual(result.status, "ready")
        self.assertNotIn("API model pin", result.detail)

    def test_non_api_adapter_no_warning(self):
        cls = _make_adapter_class("some-local-adapter", "whatever")
        with _env(PEIRA_API_PINS_TEST_KEY="x"):
            result = check_adapter(cls, SystemInfo())
        self.assertNotIn("API model pin", result.detail)

    def test_warning_survives_missing_key(self):
        # The pin warning is independent of key readiness.
        cls = _make_adapter_class("openai-structured", "gpt-5.6-luna")
        with _env(PEIRA_API_PINS_TEST_KEY=""):
            result = check_adapter(cls, SystemInfo())
        self.assertEqual(result.status, "missing_api_key")
        self.assertIn("API model pin", result.detail)
        self.assertIn("gpt-5.6-luna-2026-08-01", result.hint)


if __name__ == "__main__":
    unittest.main()
