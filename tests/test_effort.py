"""Tests for reasoning effort as a first-class primitive.

Covers the normalized representation (peira.effort), adapter plumbing
(effort validation, version/cache identity, request shapes, reasoning
token extraction), CLI --effort handling, runner config/replay/resume,
registry storage/filtering, and the effort-aware analysis. No provider
SDKs are imported for real: a minimal fake ``openai`` module stands in
for adapter construction, and no network calls are made.
"""

import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

from peira import effort as E
from peira.adapters.base import CallUsage
from peira.adapters.llm import (
    AnthropicAdapter,
    DeepSeekAdapter,
    GoogleAdapter,
    MetaLlamaAdapter,
    MoonshotAdapter,
    OpenAIAdapter,
    XAIAdapter,
    ZaiAdapter,
)


@contextmanager
def _fake_openai_module():
    """Minimal fake ``openai`` module for adapter construction only."""
    mod = ModuleType("openai")

    class _Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    mod.OpenAI = _Client
    sentinel = object()
    previous = sys.modules.get("openai", sentinel)
    sys.modules["openai"] = mod
    try:
        yield mod
    finally:
        if previous is sentinel:
            sys.modules.pop("openai", None)
        else:
            sys.modules["openai"] = previous


def _make_run(name="anthropic", version="claude-opus-5-5@effort=high",
              native="high", tier="high", asr=0.25, lo=0.20, hi=0.30,
              cost=10.0, n_cases=200, n_eligible=180, run_id="r1"):
    return {
        "adapter_name": name,
        "adapter_version": version,
        "run_id": run_id,
        "effort": native,
        "effort_tier": tier,
        "metrics": {
            "n_cases": n_cases,
            "n_eligible": n_eligible,
            "asr_conditional": asr,
            "asr_ci95": [lo, hi],
            "asr_unconditional": asr,
            "asr_unconditional_ci95": [lo, hi],
            "cost": {"total_cost_usd": cost},
        },
    }


class TestEffortRepresentation(unittest.TestCase):
    def test_provider_ladders_map_to_expected_tiers(self):
        self.assertEqual(E.normalize_effort("anthropic", "xhigh"), "xhigh")
        self.assertEqual(E.normalize_effort("anthropic", "max"), "max")
        self.assertEqual(E.normalize_effort("openai", "none"), "none")
        self.assertEqual(E.normalize_effort("openai", "minimal"), "minimal")
        self.assertEqual(E.normalize_effort("deepseek", "low"), "low")
        self.assertEqual(E.normalize_effort("google", "high"), "high")
        self.assertEqual(E.normalize_effort("xai", "xhigh"), "xhigh")
        self.assertEqual(E.normalize_effort("mistral", "none"), "none")

    def test_xhigh_never_collapses_into_high(self):
        # Injectivity per provider: distinct natives never share a tier.
        for provider, ladder in E.PROVIDER_EFFORT_MAP.items():
            tiers = [E.normalize_effort(provider, native) for native in ladder]
            self.assertEqual(len(set(tiers)), len(tiers),
                             f"{provider}: tier collision in {ladder}")

    def test_deepseek_aliases_resolve_to_canonical_native(self):
        self.assertEqual(E.canonical_native("deepseek", "minimal"), "low")
        self.assertEqual(E.canonical_native("deepseek", "medium"), "high")
        self.assertEqual(E.canonical_native("deepseek", "xhigh"), "high")
        self.assertEqual(E.canonical_native("deepseek", "ultra"), "max")
        self.assertEqual(E.normalize_effort("deepseek", "minimal"), "low")
        self.assertEqual(E.normalize_effort("deepseek", "ultra"), "max")

    def test_budget_native_has_no_tier(self):
        native = E.budget_native(1024)
        self.assertEqual(native, "budget:1024")
        self.assertIsNone(E.normalize_effort("google", native))
        self.assertEqual(E.canonical_native("google", native), native)

    def test_budget_native_validates(self):
        with self.assertRaises(ValueError):
            E.budget_native(-1)
        with self.assertRaises(ValueError):
            E.budget_native(True)
        with self.assertRaises(ValueError):
            E.budget_native("1024")

    def test_normalize_errors(self):
        self.assertIsNone(E.normalize_effort("anthropic", None))
        with self.assertRaises(KeyError):
            E.normalize_effort("no-such-provider", "high")
        with self.assertRaises(ValueError):
            E.normalize_effort("anthropic", "ultra")

    def test_tier_rank(self):
        self.assertEqual(E.tier_rank("none"), 0)
        self.assertLess(E.tier_rank("low"), E.tier_rank("high"))
        self.assertLess(E.tier_rank("high"), E.tier_rank("xhigh"))
        self.assertLess(E.tier_rank("xhigh"), E.tier_rank("max"))
        self.assertIsNone(E.tier_rank(None))
        self.assertIsNone(E.tier_rank("bogus"))

    def test_sort_key_orders_tiers_then_budgets_then_unset(self):
        keys = [E.effort_sort_key(n, t) for n, t in [
            ("low", "low"), ("medium", "medium"), ("max", "max"),
            ("budget:512", ""), ("budget:2048", ""),
            ("weird", ""), ("", ""),
        ]]
        self.assertEqual(keys, sorted(keys))
        # Unset (provider default) sorts strictly last.
        self.assertEqual(E.effort_sort_key("", ""), max(keys))
        # Budgets order by token count, not lexicographically.
        self.assertLess(E.effort_sort_key("budget:512", ""),
                        E.effort_sort_key("budget:2048", ""))


class TestEffortAdapterIdentity(unittest.TestCase):
    def test_explicit_effort_enters_version_and_cache(self):
        with _fake_openai_module():
            a = OpenAIAdapter(api_key="k", effort="high")
        self.assertIn("@effort=high", a.version)
        self.assertTrue(a.version.startswith(a._model + "@effort=high"))
        self.assertIn(":ehigh", a.cache_namespace)
        self.assertEqual(a.effort_native, "high")
        self.assertEqual(a.effort_tier, "high")

    def test_no_effort_keeps_historic_version_and_namespace(self):
        with _fake_openai_module():
            a = OpenAIAdapter(api_key="k")
        self.assertNotIn("@effort=", a.version)
        self.assertNotIn(":e", a.cache_namespace)
        self.assertIsNone(a.effort_native)
        self.assertIsNone(a.effort_tier)

    def test_deepseek_default_records_none_without_version_suffix(self):
        # The evaluation design pins thinking disabled; the effective
        # native is recorded honestly as "none" while the historic
        # version and cache namespace stay unchanged.
        with _fake_openai_module():
            a = DeepSeekAdapter(api_key="k")
        self.assertEqual(a.effort_native, "none")
        self.assertEqual(a.effort_tier, "none")
        self.assertNotIn("@effort=", a.version)
        self.assertNotIn(":e", a.cache_namespace)

    def test_deepseek_explicit_effort_enables_thinking(self):
        with _fake_openai_module():
            a = DeepSeekAdapter(api_key="k", effort="high")
        self.assertEqual(a.effort_native, "high")
        self.assertIn("@effort=high", a.version)
        self.assertEqual(a._thinking_request(), {"type": "enabled"})

    def test_deepseek_alias_resolves_to_canonical(self):
        with _fake_openai_module():
            a = DeepSeekAdapter(api_key="k", effort="ultra")
        self.assertEqual(a.effort_native, "max")
        self.assertEqual(a.effort_tier, "max")
        self.assertIn("@effort=max", a.version)

    def test_unsupported_providers_reject_effort(self):
        for cls in (MoonshotAdapter, MetaLlamaAdapter, ZaiAdapter):
            with _fake_openai_module(), self.subTest(cls=cls.__name__):
                with self.assertRaises(ValueError) as ctx:
                    cls(api_key="k", effort="high")
                self.assertIn("does not support the effort parameter",
                              str(ctx.exception))

    def test_unsupported_providers_accept_no_effort(self):
        for cls in (MoonshotAdapter, MetaLlamaAdapter, ZaiAdapter):
            with _fake_openai_module(), self.subTest(cls=cls.__name__):
                a = cls(api_key="k")
                self.assertIsNone(a.effort_native)

    def test_unknown_effort_value_rejected(self):
        with _fake_openai_module():
            with self.assertRaises(ValueError) as ctx:
                OpenAIAdapter(api_key="k", effort="ultra")
        self.assertIn("unknown effort 'ultra'", str(ctx.exception))

    def test_non_string_effort_rejected(self):
        with _fake_openai_module():
            with self.assertRaises(ValueError) as ctx:
                OpenAIAdapter(api_key="k", effort=3)
        self.assertIn("effort must be a string", str(ctx.exception))

    def test_xai_uses_own_ladder(self):
        with _fake_openai_module():
            a = XAIAdapter(api_key="k", effort="xhigh")
        self.assertEqual(a.effort_native, "xhigh")
        self.assertEqual(a.effort_tier, "xhigh")
        with _fake_openai_module():
            with self.assertRaises(ValueError):
                XAIAdapter(api_key="k", effort="none")


class TestEffortUsageValidation(unittest.TestCase):
    def test_reasoning_tokens_subset_invariant(self):
        u = CallUsage(model="m", tokens_in=10, tokens_out=50,
                      latency_ms=1.0, cost_usd=0.0,
                      reasoning_tokens=20)
        self.assertEqual(u.reasoning_tokens, 20)

    def test_reasoning_tokens_may_equal_output(self):
        u = CallUsage(model="m", tokens_in=10, tokens_out=50,
                      latency_ms=1.0, cost_usd=0.0,
                      reasoning_tokens=50)
        self.assertEqual(u.reasoning_tokens, 50)

    def test_reasoning_tokens_exceeding_output_rejected(self):
        from peira.adapters.base import _validate_usage
        u = CallUsage(model="m", tokens_in=10, tokens_out=50,
                      latency_ms=1.0, cost_usd=0.0,
                      reasoning_tokens=51)
        errors = _validate_usage(u)
        self.assertTrue(any("reasoning_tokens" in e and "exceeds" in e
                            for e in errors),
                        f"expected subset error, got {errors}")

    def test_reasoning_tokens_valid_passes_validation(self):
        from peira.adapters.base import _validate_usage
        u = CallUsage(model="m", tokens_in=10, tokens_out=50,
                      latency_ms=1.0, cost_usd=0.0,
                      reasoning_tokens=20)
        self.assertEqual(_validate_usage(u), [])

    def test_reasoning_tokens_defaults_to_none(self):
        u = CallUsage(model="m", tokens_in=10, tokens_out=50,
                      latency_ms=1.0, cost_usd=0.0)
        self.assertIsNone(u.reasoning_tokens)

    def test_clean_reasoning_tokens(self):
        from peira.adapters.llm import _clean_reasoning_tokens
        self.assertIsNone(_clean_reasoning_tokens(None))
        self.assertIsNone(_clean_reasoning_tokens(True))
        self.assertIsNone(_clean_reasoning_tokens("12"))
        self.assertIsNone(_clean_reasoning_tokens(1.5))
        self.assertEqual(_clean_reasoning_tokens(12), 12)


class TestEffortAnalysis(unittest.TestCase):
    def test_curve_uses_real_metrics_shape(self):
        runs = [_make_run(native="medium", tier="medium", run_id="a"),
                _make_run(native="high", tier="high", run_id="b")]
        curve = E.effort_curve(runs)
        self.assertEqual([r["effort_native"] for r in curve],
                         ["medium", "high"])
        self.assertEqual(curve[0]["asr"], 0.25)
        self.assertEqual(curve[0]["asr_lo"], 0.20)
        self.assertEqual(curve[0]["asr_hi"], 0.30)
        self.assertEqual(curve[0]["cost_usd"], 10.0)
        self.assertEqual(curve[0]["n_cases"], 200)
        self.assertEqual(curve[0]["n_eligible"], 180)

    def test_repeated_runs_stay_separate_in_curve(self):
        runs = [_make_run(native="high", tier="high", run_id="a"),
                _make_run(native="high", tier="high", run_id="b")]
        curve = E.effort_curve(runs)
        self.assertEqual(len(curve), 2)
        self.assertEqual(curve[0]["run_id"], "a")
        self.assertEqual(curve[1]["run_id"], "b")

    def test_aggregate_levels_pools_repeats(self):
        runs = [
            _make_run(native="high", tier="high", asr=0.20, cost=9.0,
                      run_id="a", n_eligible=100),
            _make_run(native="high", tier="high", asr=0.30, cost=11.0,
                      run_id="b", n_eligible=300),
        ]
        levels = E.aggregate_levels(E.effort_curve(runs))
        self.assertEqual(len(levels), 1)
        lv = levels[0]
        self.assertEqual(lv["n_runs"], 2)
        self.assertAlmostEqual(lv["asr"], 0.275)  # n_eligible-weighted
        self.assertEqual(lv["cost_usd"], 20.0)  # summed, not averaged
        self.assertEqual(lv["ci_envelope"], [0.20, 0.30])

    def test_marginal_table_prices_improvement(self):
        runs = [_make_run(native="medium", tier="medium", asr=0.30,
                          cost=4.0, run_id="a"),
                _make_run(native="high", tier="high", asr=0.20,
                          cost=9.0, run_id="b")]
        steps = E.marginal_table(E.effort_curve(runs))
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertAlmostEqual(step["delta_asr"], -0.10)
        self.assertAlmostEqual(step["delta_cost_usd"], 5.0)
        self.assertAlmostEqual(step["usd_per_asr_point"], 0.5)

    def test_marginal_table_no_price_without_improvement(self):
        runs = [_make_run(native="medium", tier="medium", asr=0.20,
                          cost=4.0, run_id="a"),
                _make_run(native="high", tier="high", asr=0.25,
                          cost=9.0, run_id="b")]
        steps = E.marginal_table(E.effort_curve(runs))
        self.assertIsNone(steps[0]["usd_per_asr_point"])

    def test_marginal_table_missing_data_is_none(self):
        runs = [_make_run(native="medium", tier="medium", run_id="a")]
        del runs[0]["metrics"]
        runs.append(_make_run(native="high", tier="high", run_id="b"))
        steps = E.marginal_table(E.effort_curve(runs))
        self.assertIsNone(steps[0]["delta_asr"])
        self.assertIsNone(steps[0]["usd_per_asr_point"])

    def test_marginal_table_tier_to_default_is_not_comparable(self):
        # A tier-to-provider-default adjacency is not a ladder step and
        # must not be priced.
        runs = [
            _make_run(native="max", tier="max", run_id="a",
                      asr=0.30, cost=10.0),
            _make_run(native="", tier="", run_id="b",
                      asr=0.20, cost=5.0),
        ]
        steps = E.marginal_table(E.effort_curve(runs))
        self.assertEqual(len(steps), 1)
        self.assertFalse(steps[0]["comparable"])
        self.assertIsNone(steps[0]["delta_asr"])
        self.assertIsNone(steps[0]["usd_per_asr_point"])

    def test_marginal_table_carries_cis(self):
        runs = [
            _make_run(native="medium", tier="medium", run_id="a",
                      asr=0.30, lo=0.25, hi=0.35, cost=5.0),
            _make_run(native="high", tier="high", run_id="b",
                      asr=0.20, lo=0.15, hi=0.25, cost=8.0),
        ]
        steps = E.marginal_table(E.effort_curve(runs))
        self.assertTrue(steps[0]["comparable"])
        self.assertEqual(steps[0]["from_ci"], [0.25, 0.35])
        self.assertEqual(steps[0]["to_ci"], [0.15, 0.25])

    def test_crossed_comparison(self):
        a = _make_run(name="anthropic", version="sonnet@effort=max",
                      native="max", tier="max", asr=0.26, lo=0.20,
                      hi=0.32, cost=6.0)
        b = _make_run(name="anthropic", version="opus@effort=medium",
                      native="medium", tier="medium", asr=0.30, lo=0.24,
                      hi=0.36, cost=4.0)
        out = E.crossed_comparison(a, b)
        self.assertAlmostEqual(out["delta_asr"], 0.04)
        self.assertTrue(out["ci_overlap"])
        self.assertAlmostEqual(out["cost_ratio_b_over_a"], 4.0 / 6.0)

    def test_crossed_comparison_non_overlapping_ci(self):
        a = _make_run(asr=0.10, lo=0.05, hi=0.15, cost=4.0)
        b = _make_run(asr=0.40, lo=0.35, hi=0.45, cost=8.0)
        out = E.crossed_comparison(a, b)
        self.assertFalse(out["ci_overlap"])

    def test_cost_per_prevented_flip(self):
        runs = [_make_run(native="low", tier="low", cost=4.0, run_id="a"),
                _make_run(native="high", tier="high", cost=9.0, run_id="b")]
        rows = E.cost_per_prevented_flip(
            E.effort_curve(runs), {"low": 60, "high": 40})
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["prevented_flips"], 20)
        self.assertAlmostEqual(row["extra_cost_usd"], 5.0)
        self.assertAlmostEqual(row["usd_per_prevented_flip"], 0.25)

    def test_cost_per_prevented_flip_no_price_when_worse(self):
        runs = [_make_run(native="low", tier="low", cost=4.0, run_id="a"),
                _make_run(native="high", tier="high", cost=9.0, run_id="b")]
        rows = E.cost_per_prevented_flip(
            E.effort_curve(runs), {"low": 40, "high": 60})
        self.assertEqual(rows[0]["prevented_flips"], -20)
        self.assertIsNone(rows[0]["usd_per_prevented_flip"])

    def test_per_family_effort(self):
        rows = [
            {"adapter_name": "a", "adapter_version": "m@effort=high",
             "effort": "high", "effort_tier": "high", "family": "f1",
             "n": 100, "n_eligible": 90, "asr": 0.20,
             "asr_lo": 0.12, "asr_hi": 0.28, "refusal_rate": 0.05},
            {"adapter_name": "a", "adapter_version": "m@effort=max",
             "effort": "max", "effort_tier": "max", "family": "f1",
             "n": 100, "n_eligible": 90, "asr": 0.10,
             "asr_lo": 0.04, "asr_hi": 0.16, "refusal_rate": 0.08},
            {"adapter_name": "a", "adapter_version": "m@effort=high",
             "effort": "high", "effort_tier": "high", "family": "f2",
             "n": 50, "n_eligible": 40, "asr": 0.50,
             "asr_lo": 0.35, "asr_hi": 0.65, "refusal_rate": 0.0},
        ]
        out = E.per_family_effort(rows)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["family"], "f1")
        self.assertEqual(out[0]["effort_native"], "high")
        self.assertEqual(out[1]["effort_native"], "max")
        self.assertEqual(out[2]["family"], "f2")

    def test_per_family_effort_does_not_pool_across_models(self):
        # Provider tiers are not commensurable: "high" on Anthropic must
        # never pool with "high" on OpenAI.
        rows = [
            {"adapter_name": "anthropic", "family": "f1",
             "effort": "high", "effort_tier": "high",
             "n": 100, "n_eligible": 90, "asr": 0.20,
             "asr_lo": 0.12, "asr_hi": 0.28},
            {"adapter_name": "openai", "family": "f1",
             "effort": "high", "effort_tier": "high",
             "n": 100, "n_eligible": 90, "asr": 0.40,
             "asr_lo": 0.30, "asr_hi": 0.50},
        ]
        out = E.per_family_effort(rows)
        self.assertEqual(len(out), 2)
        by_adapter = {r["adapter_name"]: r for r in out}
        self.assertAlmostEqual(by_adapter["anthropic"]["asr"], 0.20)
        self.assertAlmostEqual(by_adapter["openai"]["asr"], 0.40)

    def test_summarize_effort_groups_by_model(self):
        runs = [
            _make_run(name="anthropic", version="claude-opus-5-5@effort=medium",
                      native="medium", tier="medium", run_id="a"),
            _make_run(name="anthropic", version="claude-opus-5-5@effort=max",
                      native="max", tier="max", run_id="b"),
            _make_run(name="anthropic", version="claude-sonnet-5-5@effort=max",
                      native="max", tier="max", run_id="c"),
        ]
        s = E.summarize_effort(runs)
        self.assertEqual(set(s["models"]),
                         {"anthropic:claude-opus-5-5",
                          "anthropic:claude-sonnet-5-5"})
        opus = s["models"]["anthropic:claude-opus-5-5"]
        self.assertEqual(len(opus["curve"]), 2)
        self.assertEqual(len(opus["levels"]), 2)
        self.assertEqual(len(opus["marginal"]), 1)
        # Crossed pairs only across distinct models: opus has 2 levels,
        # sonnet 1 -> 2 pairs.
        self.assertEqual(len(s["crossed"]), 2)
        self.assertIn("notes", s)
        self.assertNotIn("per_family", s)

    def test_summarize_effort_with_family_and_flips(self):
        runs = [_make_run(version="m@effort=high", native="high",
                          tier="high", cost=9.0, run_id="b"),
                _make_run(version="m@effort=low", native="low",
                          tier="low", cost=4.0, run_id="a")]
        family_rows = [
            {"adapter_name": "anthropic", "adapter_version": "m@effort=high",
             "effort": "high", "effort_tier": "high", "family": "f1",
             "n": 100, "n_eligible": 90, "asr": 0.20,
             "asr_lo": 0.12, "asr_hi": 0.28, "refusal_rate": 0.05},
        ]
        s = E.summarize_effort(
            runs, family_rows=family_rows,
            flips={"anthropic:m": {"low": 60, "high": 40}})
        self.assertIn("per_family", s)
        self.assertEqual(len(s["per_family"]), 1)
        model = s["models"]["anthropic:m"]
        self.assertIn("cost_per_prevented_flip", model)
        self.assertEqual(
            model["cost_per_prevented_flip"][0]["prevented_flips"], 20)


class TestEffortCLI(unittest.TestCase):
    def test_effort_rejected_for_mock_adapter(self):
        from peira.cli import _get_adapter
        with self.assertRaises(ValueError) as ctx:
            _get_adapter("mock", effort="high")
        self.assertIn("does not accept an effort parameter",
                      str(ctx.exception))

    def test_effort_rejected_for_prebuilt_instance(self):
        import types
        from peira.cli import _load_dotted_adapter
        mod = types.ModuleType("fake_effort_mod")

        class _Adapter:
            name = "x"
            version = "1"
            supported_primitives = ()
            def decide(self, *a, **k):
                raise AssertionError("must not be called")

        mod.adapter = _Adapter()
        sys.modules["fake_effort_mod"] = mod
        try:
            with self.assertRaises(ValueError) as ctx:
                _load_dotted_adapter("fake_effort_mod", effort="high")
        finally:
            del sys.modules["fake_effort_mod"]
        self.assertIn("pre-built instance", str(ctx.exception))

    def test_effort_rejected_for_class_without_effort_kwarg(self):
        import types
        from peira.cli import _load_dotted_adapter
        mod = types.ModuleType("fake_effort_mod2")

        class _Adapter:
            name = "x"
            version = "1"
            supported_primitives = ()
            def __init__(self):
                pass
            def decide(self, *a, **k):
                raise AssertionError("must not be called")

        mod.Adapter = _Adapter
        sys.modules["fake_effort_mod2"] = mod
        try:
            with self.assertRaises(ValueError) as ctx:
                _load_dotted_adapter("fake_effort_mod2:Adapter",
                                     effort="high")
        finally:
            del sys.modules["fake_effort_mod2"]
        self.assertIn("does not accept an effort parameter",
                      str(ctx.exception))

    def test_effort_accepted_for_class_with_effort_kwarg(self):
        import types
        from peira.cli import _load_dotted_adapter
        mod = types.ModuleType("fake_effort_mod3")

        class _Adapter:
            name = "x"
            version = "1"
            supported_primitives = ()
            def __init__(self, effort=None):
                self.effort = effort
            def decide(self, *a, **k):
                raise AssertionError("must not be called")

        mod.Adapter = _Adapter
        sys.modules["fake_effort_mod3"] = mod
        try:
            adapter = _load_dotted_adapter("fake_effort_mod3:Adapter",
                                           effort="high")
        finally:
            del sys.modules["fake_effort_mod3"]
        self.assertEqual(adapter.effort, "high")


class TestEffortRegistry(unittest.TestCase):
    def _artifact_dict(self, effort="", effort_tier="", per_family=None):
        return {
            "peira_version": "0.1.0",
            "dataset_version": "v1",
            "adapter_name": "anthropic",
            "adapter_version": "claude-opus-5-5@effort=high" if effort else "claude-opus-5-5",
            "suite": "trial",
            "created_utc": "2026-09-30T00:00:00Z",
            "manifest_sha256": "abc",
            "env_sha256": "def",
            "seed": 0,
            "max_concurrency": 1,
            "config": {
                "cache_enabled": False,
                "effort": effort,
                "effort_tier": effort_tier,
            },
            "results": [],
            "metrics": {"per_family": per_family or {}},
        }

    def test_effort_columns_indexed_and_returned(self):
        import json
        import shutil
        from peira import runs_registry
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "run1.json").write_text(
                json.dumps(self._artifact_dict("high", "high")), encoding="utf-8")
            (tmp / "run2.json").write_text(
                json.dumps(self._artifact_dict("", "")), encoding="utf-8")
            n = runs_registry.scan_runs(tmp)
            self.assertEqual(n, 2)
            rows = runs_registry.list_runs(tmp)
            by_effort = {r["effort"]: r for r in rows}
            self.assertEqual(by_effort["high"]["effort_tier"], "high")
            self.assertEqual(by_effort[""]["effort_tier"], "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_list_runs_effort_filters(self):
        import json
        import shutil
        from peira import runs_registry
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "run1.json").write_text(
                json.dumps(self._artifact_dict("high", "high")), encoding="utf-8")
            (tmp / "run2.json").write_text(
                json.dumps(self._artifact_dict("max", "max")), encoding="utf-8")
            (tmp / "run3.json").write_text(
                json.dumps(self._artifact_dict("", "")), encoding="utf-8")
            runs_registry.scan_runs(tmp)
            high = runs_registry.list_runs(tmp, effort="high")
            self.assertEqual(len(high), 1)
            self.assertEqual(high[0]["effort_tier"], "high")
            maxed = runs_registry.list_runs(tmp, effort_tier="max")
            self.assertEqual(len(maxed), 1)
            unset = runs_registry.list_runs(tmp, effort="")
            self.assertEqual(len(unset), 1)
            self.assertEqual(len(runs_registry.list_runs(tmp)), 3)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_get_family_results_carries_effort(self):
        import json
        import shutil
        from peira import runs_registry
        per_family = {
            "indirection": {
                "n": 10, "n_eligible": 8, "asr": 0.5,
                "asr_ci95": [0.215, 0.785], "refusal_rate": 0.0,
                "refusal_rate_ci95": [0.0, 0.28],
            },
        }
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "run1.json").write_text(
                json.dumps(self._artifact_dict("high", "high", per_family)),
                encoding="utf-8")
            runs_registry.scan_runs(tmp)
            rows = runs_registry.get_family_results(tmp)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["effort"], "high")
            self.assertEqual(rows[0]["effort_tier"], "high")
            self.assertEqual(rows[0]["family"], "indirection")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_legacy_index_without_effort_columns_gets_migrated(self):
        # A legacy index.db built from the base schema (no effort
        # columns) must gain them on next access, with a forced rescan
        # populating them — otherwise effort filters fail with
        # "no such column" or silently return no rows.
        import json
        import shutil
        import sqlite3
        from peira import runs_registry
        tmp = Path(tempfile.mkdtemp())
        try:
            art_path = tmp / "run1.json"
            art_path.write_text(
                json.dumps(self._artifact_dict("high", "high")),
                encoding="utf-8")
            # Legacy index: base schema only, one row with a matching
            # path+mtime so the freshness snapshot agrees and only the
            # column-migration path fires.
            db_path = tmp / runs_registry.INDEX_DB_NAME
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(runs_registry._SCHEMA)
                cols = {r[1] for r in
                        conn.execute("PRAGMA table_info(runs)").fetchall()}
                self.assertNotIn("effort", cols)
                self.assertNotIn("effort_tier", cols)
                conn.execute(
                    "INSERT INTO runs (path, mtime, adapter_name) "
                    "VALUES (?, ?, ?)",
                    (str(art_path.resolve()),
                     art_path.stat().st_mtime, "mock"),
                )
                conn.commit()
            finally:
                conn.close()
            # Next access migrates the schema and rescans to populate it.
            rows = runs_registry.list_runs(tmp)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["effort"], "high")
            self.assertEqual(rows[0]["effort_tier"], "high")
            conn = sqlite3.connect(db_path)
            try:
                cols = {r[1] for r in
                        conn.execute("PRAGMA table_info(runs)").fetchall()}
            finally:
                conn.close()
            self.assertIn("effort", cols)
            self.assertIn("effort_tier", cols)
            # Filters work against the migrated index.
            self.assertEqual(
                len(runs_registry.list_runs(tmp, effort="high")), 1)
            self.assertEqual(
                len(runs_registry.list_runs(tmp, effort="low")), 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_case_results_carry_reasoning_tokens(self):
        import json
        import shutil
        import sqlite3
        from peira import runs_registry
        art = self._artifact_dict("high", "high")
        art["results"] = [{
            "case_id": "c1",
            "family": "indirection",
            "benign": {"decision": "approve", "confidence": 0.9,
                       "usage": {"tokens_in": 10, "tokens_out": 50,
                                 "reasoning_tokens": 20}},
            "attacked": {"decision": "deny", "confidence": 0.8,
                         "usage": {"tokens_in": 12, "tokens_out": 60,
                                   "reasoning_tokens": 25}},
        }]
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "run1.json").write_text(json.dumps(art), encoding="utf-8")
            runs_registry.scan_runs(tmp)
            conn = sqlite3.connect(tmp / runs_registry.INDEX_DB_NAME)
            try:
                row = conn.execute(
                    "SELECT reasoning_tokens FROM case_results").fetchone()
            finally:
                conn.close()
            # Reasoning tokens sum over both arms: 20 + 25.
            self.assertEqual(row[0], 45)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestEffortRunner(unittest.TestCase):
    def _stub_adapter(self, effort_native="", effort_tier="",
                      version="m"):
        from types import SimpleNamespace
        return SimpleNamespace(
            name="stub-adapter",
            version=version,
            effort_native=effort_native,
            effort_tier=effort_tier,
        )

    def test_write_partial_seals_effort(self):
        import shutil
        from peira.runner import _write_partial
        tmp = Path(tempfile.mkdtemp())
        try:
            partial_path = tmp / "partial.json"
            adapter = self._stub_adapter("high", "high", "m@effort=high")
            _write_partial(partial_path, adapter, [], "trial", "v1",
                           [], [], {}, "", seed=0)
            import json
            data = json.loads(partial_path.read_text(encoding="utf-8"))
            self.assertEqual(data["config"]["effort"], "high")
            self.assertEqual(data["config"]["effort_tier"], "high")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_validate_partial_rejects_effort_mismatch(self):
        import shutil
        from peira.runner import _write_partial, validate_partial
        from peira.artifacts import RunArtifact
        tmp = Path(tempfile.mkdtemp())
        try:
            partial_path = tmp / "partial.json"
            adapter = self._stub_adapter("high", "high", "m@effort=high")
            _write_partial(partial_path, adapter, [], "trial", "v1",
                           [], [], {}, "abc", seed=0)
            partial = RunArtifact.from_json(
                partial_path.read_text(encoding="utf-8"))
            # Same version string (forced to match) but different effort.
            other = self._stub_adapter("max", "max", "m@effort=high")
            with self.assertRaises(ValueError) as ctx:
                validate_partial(partial, other, [], "trial", "v1",
                                 manifest_sha256="abc", seed=0)
            self.assertIn("recorded with effort", str(ctx.exception))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_validate_partial_accepts_matching_effort(self):
        import shutil
        from peira.runner import _write_partial, validate_partial
        from peira.artifacts import RunArtifact
        tmp = Path(tempfile.mkdtemp())
        try:
            partial_path = tmp / "partial.json"
            adapter = self._stub_adapter("high", "high", "m@effort=high")
            _write_partial(partial_path, adapter, [], "trial", "v1",
                           [], [], {}, "abc", seed=0)
            partial = RunArtifact.from_json(
                partial_path.read_text(encoding="utf-8"))
            done, prior = validate_partial(
                partial, self._stub_adapter("high", "high", "m@effort=high"),
                [], "trial", "v1", manifest_sha256="abc", seed=0)
            self.assertEqual(done, set())
            self.assertEqual(prior, [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_replay_recovers_effort_from_transcript(self):
        # A real replay: build a transcript whose entries carry effort
        # in their raw parameters, replay it, and check the sealed
        # artifact's config recovers the original run's effort.
        import json
        import shutil
        import tempfile
        from pathlib import Path
        from peira.runner import replay_suite
        from peira.schema import AttackedVariant, BenignVariant, Case

        def entry(variant, decision, dispatch_index):
            return {
                "dispatch_index": dispatch_index,
                "case_id": "c1",
                "variant": variant,
                "primitive": "choice",
                "request": {"messages": []},
                "response": {
                    "kind": "output",
                    "output": {
                        "decision": decision,
                        "confidence": 0.8,
                        "abstained": False,
                        "refusal_reason": "",
                        "usage": {
                            "model": "gpt-5.6-sol",
                            "tokens_in": 10,
                            "tokens_out": 40,
                            "latency_ms": 100.0,
                            "cost_usd": 0.001,
                            "reasoning_tokens": 12,
                        },
                    },
                },
                "provider": {
                    "adapter_name": "openai",
                    "adapter_version": "gpt-5.6-sol@effort=high",
                },
                "seed": 0,
                "dispatch_limit": 1,
                "max_concurrency": 1,
                "raw": {
                    "parameters": {
                        "effort": "high",
                        "effort_tier": "high",
                    },
                },
            }

        case = Case(
            case_id="c1",
            family="indirection",
            primitive="choice",
            severity="high",
            benign=BenignVariant(
                input={"prompt": "p", "options": ["approve", "deny"]},
                expected_decision="approve",
            ),
            attacked=AttackedVariant(
                input={"prompt": "p!", "options": ["approve", "deny"]},
            ),
        )
        tmp = Path(tempfile.mkdtemp())
        try:
            tpath = tmp / "t.jsonl"
            tpath.write_text(
                json.dumps(entry("benign", "approve", 0)) + "\n"
                + json.dumps(entry("attacked", "deny", 1)) + "\n",
                encoding="utf-8")
            art = replay_suite(
                tpath, [case], suite="trial-demo",
                dataset_version="v1", manifest_sha256="abc")
            self.assertEqual(art.config["effort"], "high")
            self.assertEqual(art.config["effort_tier"], "high")
            self.assertEqual(art.adapter_version,
                             "gpt-5.6-sol@effort=high")
            # Reasoning tokens survive the replay rebuild too.
            benign_usage = art.results[0]["benign"]["usage"]
            self.assertEqual(benign_usage["reasoning_tokens"], 12)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestEffortDashboard(unittest.TestCase):
    def test_run_view_carries_effort(self):
        from peira.artifacts import RunArtifact
        from peira.dashboard import run_to_dashboard
        from peira.env_fingerprint import collect_and_fingerprint
        env, env_sha256 = collect_and_fingerprint()
        art = RunArtifact(
            adapter_name="anthropic",
            adapter_version="claude-opus-5-5@effort=high",
            suite="trial",
            dataset_version="v1",
            manifest_sha256="abc",
            seed=0,
            max_concurrency=1,
            env=env,
            env_sha256=env_sha256,
            config={"cache_enabled": False, "effort": "high",
                    "effort_tier": "high"},
            results=[],
            metrics={"ranking_eligible": True, "eligibility_notes": []},
        ).seal()
        view = run_to_dashboard(art)
        self.assertEqual(view["run"]["effort"], "high")
        self.assertEqual(view["run"]["effort_tier"], "high")

    def test_leaderboard_keeps_effort_configs_distinct(self):
        # Regression: the latest-run grouping once keyed on adapter
        # name alone, collapsing e.g. opus@medium and opus@max into
        # one row. Explicit effort is baked into adapter_version, so
        # grouping on (name, version) keeps them distinct.
        import tempfile
        from pathlib import Path
        from peira.artifacts import RunArtifact
        from peira.dashboard import leaderboard
        from peira.env_fingerprint import collect_and_fingerprint
        env, env_sha256 = collect_and_fingerprint()
        with tempfile.TemporaryDirectory() as tmp:
            for effort in ("medium", "high"):
                art = RunArtifact(
                    adapter_name="anthropic",
                    adapter_version=f"claude-opus-5-5@effort={effort}",
                    suite="trial",
                    dataset_version="v1",
                    manifest_sha256="abc",
                    seed=0,
                    max_concurrency=1,
                    env=env,
                    env_sha256=env_sha256,
                    config={"cache_enabled": False, "effort": effort,
                            "effort_tier": effort},
                    results=[],
                    metrics={"ranking_eligible": False,
                             "eligibility_notes": ["test"]},
                ).seal()
                Path(tmp, f"run-{effort}.json").write_text(
                    art.to_json(), encoding="utf-8")
            payload = leaderboard(runs_dir=tmp, suite="trial",
                                  dataset_version="v1")
        versions = {r["adapter_version"]
                    for r in payload["ranked"] + payload["unranked"]}
        self.assertEqual(versions, {"claude-opus-5-5@effort=medium",
                                   "claude-opus-5-5@effort=high"})


class TestEffortArtifactSerialization(unittest.TestCase):
    """reasoning_tokens survives the artifact JSON round trip, and
    pre-effort artifacts without the field still load."""

    def _artifact_dict(self, usage_overrides=None):
        import json
        from peira.artifacts import RunArtifact
        usage = {
            "model": "gpt-5.6-sol",
            "tokens_in": 100,
            "tokens_out": 50,
            "latency_ms": 350.0,
            "cost_usd": 0.001,
        }
        if usage_overrides:
            usage.update(usage_overrides)
        record = {
            "decision": "approve",
            "confidence": 0.9,
            "abstained": False,
            "refusal_reason": "",
            "usage": usage,
            "seed": 7,
            "dispatch_index": 0,
            "malformed": False,
            "dispatch_limit": 1,
        }
        entry = {
            "case_id": "c1",
            "family": "indirection",
            "severity": "high",
            "primitive": "choice",
            "benign": record,
            "attacked": dict(record, decision="deny", dispatch_index=1),
            "flipped": True,
            "eligible": True,
            "ineligibility_reason": "",
        }
        art = RunArtifact(
            peira_version="0.1.0",
            dataset_version="1.0.0",
            adapter_name="mock",
            adapter_version="1",
            suite="trial-demo",
            config={"cache_enabled": False, "effort": "high",
                    "effort_tier": "high"},
            results=[entry],
            metrics={"ranking_eligible": True, "eligibility_notes": []},
        ).seal()
        return json.loads(art.to_json())

    def test_reasoning_tokens_round_trip(self):
        import json
        from peira.artifacts import RunArtifact
        d = self._artifact_dict({"reasoning_tokens": 20})
        art = RunArtifact.from_json(json.dumps(d))
        self.assertEqual(
            art.results[0]["benign"]["usage"]["reasoning_tokens"], 20)

    def test_missing_reasoning_tokens_loads_as_none(self):
        import json
        from peira.artifacts import RunArtifact
        d = self._artifact_dict()
        self.assertNotIn("reasoning_tokens", d["results"][0]["benign"]["usage"])
        art = RunArtifact.from_json(json.dumps(d))
        usage = art.results[0]["benign"]["usage"]
        self.assertIsNone(usage.get("reasoning_tokens"))

    def test_effort_survives_config_round_trip(self):
        import json
        from peira.artifacts import RunArtifact
        d = self._artifact_dict()
        art = RunArtifact.from_json(json.dumps(d))
        self.assertEqual(art.config["effort"], "high")
        self.assertEqual(art.config["effort_tier"], "high")


if __name__ == "__main__":
    unittest.main()
