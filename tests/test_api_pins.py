"""Tests for the pinned API model registry (peira.api_pins).

The pins are the Layer 3 (Adapter) execution-methodology controls for the
four API-backed structured-output adapters. Model IDs were re-verified
against the vendor docs on 2026-09-27:

    openai:     gpt-5.6-luna
    anthropic:  claude-sonnet-5
    google:     gemini-3.8-flash
    moonshot:   kimi-k3

D3 decided 2026-10-02 (latest only): the Anthropic pin moved to
claude-sonnet-5-5.

The validator is a format + vendor-scheme check (offline by design): pin
validity is maintained by review, never probed live. These tests lock the
validator's accept/reject behavior so a future bad edit cannot silently
re-admit a fabricated ID.
"""

import unittest
from unittest.mock import patch

from peira.api_pins import (
    DEPRECATED_PINS,
    OPENROUTER_CHEAP_MODELS,
    PINNED_API_MODELS,
    DeprecatedPinError,
    UnknownAdapterPinError,
    _looks_like_any_vendor_id,
    _looks_like_pinned_id,
    _passes_vendor_semantics,
    _VENDOR_ID_PATTERNS,
    get_openrouter_cheap_model,
    get_pinned_model,
    is_pinned_model,
    pin_status,
    validate_registry,
)

# The four fabricated IDs from the original PR #112 commit. None of them
# exists in the vendor docs; the validator must reject every one.
FABRICATED_IDS = {
    "openai-structured": "gpt-5.6-luna-2026-08-01",
    "anthropic-structured": "claude-sonnet-5-20260915",
    "google-structured": "gemini-3.8-flash-001",
    "moonshot-structured": "kimi-k3-2026-08-01",
}


class TestPinnedIds(unittest.TestCase):
    def test_all_four_pins_resolve(self):
        for adapter in PINNED_API_MODELS:
            with self.subTest(adapter=adapter):
                self.assertIsInstance(get_pinned_model(adapter), str)

    def test_openai_pin_is_luna(self):
        self.assertEqual(get_pinned_model("openai-structured"), "gpt-5.6-luna")

    def test_anthropic_pin_is_sonnet_5_5(self):
        self.assertEqual(
            get_pinned_model("anthropic-structured"), "claude-sonnet-5-5"
        )

    def test_google_pin_is_gemini_38_flash(self):
        self.assertEqual(
            get_pinned_model("google-structured"), "gemini-3.8-flash"
        )

    def test_moonshot_pin_is_kimi_k3(self):
        self.assertEqual(get_pinned_model("moonshot-structured"), "kimi-k3")

    def test_pins_are_bare_ids(self):
        for adapter, pin in PINNED_API_MODELS.items():
            with self.subTest(adapter=adapter):
                self.assertNotRegex(pin, r"\d{4}-\d{2}-\d{2}")
                self.assertNotRegex(pin, r"-\d{3}$")

    def test_fabricated_ids_are_not_pins(self):
        for adapter, bad_id in FABRICATED_IDS.items():
            with self.subTest(adapter=adapter):
                self.assertNotIn(bad_id, PINNED_API_MODELS.values())
                self.assertFalse(is_pinned_model(bad_id))


class TestValidatorAccepts(unittest.TestCase):
    def test_accepts_luna(self):
        self.assertTrue(
            _looks_like_pinned_id("openai-structured", "gpt-5.6-luna")
        )

    def test_accepts_legacy_dated_openai_id(self):
        self.assertTrue(
            _looks_like_pinned_id("openai-structured", "gpt-4o-2024-08-06")
        )

    def test_accepts_sonnet_5(self):
        self.assertTrue(
            _looks_like_pinned_id("anthropic-structured", "claude-sonnet-5")
        )

    def test_accepts_dated_pre_46_anthropic_id(self):
        self.assertTrue(
            _looks_like_pinned_id(
                "anthropic-structured", "claude-opus-4-1-20250805"
            )
        )

    def test_accepts_gemini_38_flash(self):
        self.assertTrue(
            _looks_like_pinned_id("google-structured", "gemini-3.8-flash")
        )

    def test_accepts_numbered_legacy_gemini_id(self):
        self.assertTrue(
            _looks_like_pinned_id("google-structured", "gemini-2.0-flash-001")
        )

    def test_accepts_kimi_k3(self):
        self.assertTrue(
            _looks_like_pinned_id("moonshot-structured", "kimi-k3")
        )

    def test_accepts_dated_kimi_k2(self):
        self.assertTrue(
            _looks_like_pinned_id("moonshot-structured", "kimi-k2-0905")
        )


class TestValidatorRejects(unittest.TestCase):
    def test_rejects_all_four_fabricated_ids(self):
        for adapter, bad_id in FABRICATED_IDS.items():
            with self.subTest(adapter=adapter, model_id=bad_id):
                self.assertFalse(_looks_like_pinned_id(adapter, bad_id))

    def test_rejects_cross_vendor_ids(self):
        cases = [
            ("openai-structured", "claude-sonnet-5"),
            ("anthropic-structured", "gpt-5.6-luna"),
            ("google-structured", "kimi-k3"),
            ("moonshot-structured", "gemini-3.8-flash"),
        ]
        for adapter, model_id in cases:
            with self.subTest(adapter=adapter, model_id=model_id):
                self.assertFalse(_looks_like_pinned_id(adapter, model_id))

    def test_rejects_non_ids(self):
        for bad in ("latest", "", "not-a-model-id", "kimi"):
            with self.subTest(model_id=bad):
                self.assertFalse(_looks_like_any_vendor_id(bad))

    def test_unknown_adapter_fails_closed(self):
        self.assertFalse(
            _looks_like_pinned_id("unknown-structured", "gpt-5.6-luna")
        )
        self.assertFalse(_looks_like_pinned_id("", "gpt-5.6-luna"))
        self.assertFalse(_looks_like_pinned_id("openai-structured", ""))


class TestValidateRegistry(unittest.TestCase):
    def test_registry_validates(self):
        validate_registry()  # must not raise

    def test_rejects_malformed_pin(self):
        with patch.dict(PINNED_API_MODELS, {"openai-structured": "bogus"}):
            with self.assertRaises(ValueError):
                validate_registry()

    def test_rejects_fabricated_pin_in_registry(self):
        # A fabricated ID smuggled into the registry must fail validation.
        with patch.dict(
            PINNED_API_MODELS,
            {"google-structured": "gemini-3.8-flash-001"},
        ):
            with self.assertRaises(ValueError):
                validate_registry()

    def test_rejects_deprecated_pin_in_registry(self):
        with patch.dict(
            DEPRECATED_PINS, {"gpt-4o-2024-08-06": "gpt-5.6-luna"}
        ), patch.dict(
            PINNED_API_MODELS, {"openai-structured": "gpt-4o-2024-08-06"}
        ):
            with self.assertRaises(ValueError):
                validate_registry()

    def test_rejects_malformed_deprecated_entry(self):
        with patch.dict(DEPRECATED_PINS, {"not-a-model-id": "gpt-5.6-luna"}):
            with self.assertRaises(ValueError):
                validate_registry()

    def test_rejects_fabricated_deprecated_entry(self):
        # A fabricated ID cannot be smuggled in through DEPRECATED_PINS:
        # versioning-scheme rules apply to deprecation entries too.
        with patch.dict(
            DEPRECATED_PINS, {"gpt-5.6-luna-2026-08-01": "gpt-5.6-luna"}
        ):
            with self.assertRaises(ValueError):
                validate_registry()
        with patch.dict(
            DEPRECATED_PINS, {"gemini-2.0-flash-001": "gemini-3.8-flash-001"}
        ):
            with self.assertRaises(ValueError):
                validate_registry()

    def test_accepts_legacy_deprecated_entry(self):
        # Genuine retired IDs (legacy formats the scheme rules keep
        # accepting) still validate as deprecation entries.
        with patch.dict(
            DEPRECATED_PINS, {"gpt-4o-2024-08-06": "gpt-5.6-luna"}
        ):
            validate_registry()  # must not raise


class TestPinLifecycle(unittest.TestCase):
    def test_unknown_adapter_raises(self):
        with self.assertRaises(UnknownAdapterPinError):
            get_pinned_model("unknown-structured")

    def test_deprecated_pin_raises_with_replacement(self):
        with patch.dict(
            DEPRECATED_PINS, {"gpt-4o-2024-08-06": "gpt-5.6-luna"}
        ), patch.dict(
            PINNED_API_MODELS, {"openai-structured": "gpt-4o-2024-08-06"}
        ):
            with self.assertRaises(DeprecatedPinError) as ctx:
                get_pinned_model("openai-structured")
        self.assertIn("gpt-5.6-luna", str(ctx.exception))

    def test_is_pinned_model(self):
        self.assertTrue(is_pinned_model("gpt-5.6-luna"))
        self.assertTrue(is_pinned_model("kimi-k3"))
        self.assertFalse(is_pinned_model("gpt-5.6-luna-2026-08-01"))
        self.assertFalse(is_pinned_model("gpt-4o-2024-08-06"))

    def test_pin_status(self):
        status, _ = pin_status("openai-structured", "gpt-5.6-luna")
        self.assertEqual(status, "pinned")
        with patch.dict(
            DEPRECATED_PINS, {"gpt-4o-2024-08-06": "gpt-5.6-luna"}
        ):
            status, _ = pin_status("openai-structured", "gpt-4o-2024-08-06")
            self.assertEqual(status, "deprecated")
        status, _ = pin_status("openai-structured", "gpt-5.6-luna-2026-08-01")
        self.assertEqual(status, "unpinned")
        status, _ = pin_status("unknown-structured", "gpt-5.6-luna")
        self.assertEqual(status, "unknown_adapter")

    def test_pin_status_never_raises_on_bad_adapter(self):
        # The "Never raises" contract holds even for unhashable input.
        for bad in (["openai-structured"], None, 42):
            status, _ = pin_status(bad, "gpt-5.6-luna")
            self.assertEqual(status, "unknown_adapter")


class TestOpenRouterCheapModels(unittest.TestCase):
    """The cheap-model pilot set (OPENROUTER_CHEAP_MODELS)."""

    def test_all_ids_match_openrouter_format(self):
        # Every ID must be vendor/model, matching the OpenRouter gateway
        # convention enforced by the openrouter vendor regex.
        pattern = _VENDOR_ID_PATTERNS["openrouter"]
        for key, model_id in OPENROUTER_CHEAP_MODELS.items():
            with self.subTest(key=key):
                self.assertRegex(model_id, pattern)

    def test_all_ids_pass_gateway_semantics(self):
        # The module's anti-fabrication bar for gateway IDs: the inner
        # model part must match OpenRouter's documented ID shape. A
        # fabricated inner ID cannot ride in behind the slash.
        for key, model_id in OPENROUTER_CHEAP_MODELS.items():
            with self.subTest(key=key):
                self.assertTrue(
                    _passes_vendor_semantics("openrouter", model_id),
                    f"{model_id!r} fails gateway semantics",
                )

    def test_ten_models_one_per_lab(self):
        # 10 base models (one per lab) + 5 discounted additions.
        self.assertEqual(len(OPENROUTER_CHEAP_MODELS), 15)
        vendors = {mid.split("/")[0] for mid in OPENROUTER_CHEAP_MODELS.values()}
        # 13 distinct vendors: qwen and inclusionai each appear twice
        # (base + discounted).
        self.assertEqual(len(vendors), 13)

    def test_get_openrouter_cheap_model_all_bindings(self):
        # Independent literal mapping: a key-to-ID swap in the dict
        # must fail this test. (Reading expected values from the dict
        # itself would be tautological.)
        expected = {
            "or-mistral-nemo": "mistralai/mistral-nemo",
            "or-deepseek-flash": "deepseek/deepseek-v4-flash",
            "or-gpt-oss-20b": "openai/gpt-oss-20b",
            "or-qwen-flash": "qwen/qwen3.7-flash",
            "or-llama-8b": "meta-llama/llama-3.1-8b-instruct",
            "or-gemma-4b": "google/gemma-3-4b-it",
            "or-glm-flash": "z-ai/glm-4.7-flash",
            "or-kimi-k2.5": "moonshotai/kimi-k2.5",
            "or-grok-4.3": "x-ai/grok-4.3",
            "or-claude-haiku": "anthropic/claude-haiku-4.5",
            "or-mercury-2.5": "inception/mercury-2.5",
            "or-qwen3-235b": "qwen/qwen3-235b-a22b-2507",
            "or-ling-flash-vl": "inclusionai/ling-3.0-flash-vl",
            "or-solar-pro4": "upstage/solar-pro4",
            "or-ling-flash": "inclusionai/ling-3.0-flash",
        }
        self.assertEqual(OPENROUTER_CHEAP_MODELS, expected)
        for key, model_id in expected.items():
            with self.subTest(key=key):
                self.assertEqual(get_openrouter_cheap_model(key), model_id)

    def test_get_openrouter_cheap_model_fails_closed(self):
        with self.assertRaises(KeyError) as ctx:
            get_openrouter_cheap_model("or-does-not-exist")
        self.assertIn("or-mistral-nemo", str(ctx.exception))

    def test_every_cheap_model_has_pricing(self):
        from peira.pricing import load_pricing_table

        table = load_pricing_table()
        for key, model_id in OPENROUTER_CHEAP_MODELS.items():
            with self.subTest(key=key):
                self.assertIn(model_id, table["models"])


if __name__ == "__main__":
    unittest.main()
