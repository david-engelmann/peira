"""Tests for the Cursor harness adapter.

The agent CLI is faked through the adapter's injectable runner: no
subprocess, no API key, no network. The fakes return envelopes in
the live-verified shape so the tests can assert on the pin, the
usage mapping, the sampling incapability flags, and error mapping.
"""

import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from peira.adapters.cursor_harness import CursorHarnessAdapter
from peira.adapters.base import CallContext, ProviderError


CASE = {"prompt": "Should the refund be approved?",
        "options": ["approve", "deny"]}

GOOD_JSON = json.dumps({
    "decision": "approve", "confidence": 0.73, "reason": "looks fine",
})


def _envelope(text=GOOD_JSON, **over):
    env = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 100,
        "duration_api_ms": 90,
        "result": text,
        "session_id": "sess-1",
        "request_id": "req-1",
        "usage": {
            "inputTokens": 13366,
            "outputTokens": 31,
            "cacheReadTokens": 6016,
            "cacheWriteTokens": 0,
        },
    }
    env.update(over)
    return env


@contextmanager
def _env(**vars):
    old = {k: os.environ.get(k) for k in vars}
    try:
        for k, v in vars.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _ctx():
    return CallContext(call_id="call-test")


def _adapter(**over):
    kwargs = {
        "api_key": "crsr-test",
        "runner_fn": lambda prompt: _envelope(),
    }
    kwargs.update(over)
    return CursorHarnessAdapter(**kwargs)


class TestCursorHarnessConstruction(unittest.TestCase):
    def test_name(self):
        self.assertEqual(CursorHarnessAdapter.name, "cursor-harness")

    def test_default_model_is_the_cursor_variant_label(self):
        adapter = _adapter()
        self.assertEqual(adapter.version, "grok-4.7-high-fast")

    def test_default_model_matches_pin_registry(self):
        from peira.api_pins import PINNED_API_MODELS
        self.assertEqual(
            PINNED_API_MODELS["cursor-harness"], "grok-4.7-high-fast")

    def test_bare_vendor_id_is_rejected(self):
        # grok-4.7 is xAI's id. The harness surface answers under
        # Cursor's variant label, and the pin must say so.
        with self.assertRaises(ValueError):
            _adapter(model="grok-4.7")

    def test_sampling_is_provider_incapable(self):
        adapter = _adapter()
        self.assertFalse(adapter._supports_temperature)
        self.assertFalse(adapter._supports_seed)
        self.assertIsNone(adapter._sent_seed())

    def test_missing_key_names_cursor_env_var(self):
        # The base class resolves the key and its message is the one
        # that surfaces; assert the surfaced text, not just the
        # variable name appearing anywhere.
        with _env(CURSOR_API_KEY=None):
            with self.assertRaises(ValueError) as ctx:
                CursorHarnessAdapter(
                    runner_fn=lambda prompt: _envelope())
        self.assertIn("CURSOR_API_KEY is not set", str(ctx.exception))


class TestCursorHarnessCalls(unittest.TestCase):
    def test_decide_parses_agent_json(self):
        seen = {}

        def runner(prompt):
            seen["prompt"] = prompt
            return _envelope()

        adapter = _adapter(runner_fn=runner)
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        # The structured pipeline's composed prompt is what was sent.
        self.assertIn("Should the refund be approved?", seen["prompt"])

    def test_usage_comes_from_the_envelope(self):
        adapter = _adapter()
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.usage.model, "grok-4.7-high-fast")
        # Cursor's components are disjoint: total input is the sum.
        self.assertEqual(out.usage.tokens_in, 13366 + 6016)
        self.assertEqual(out.usage.tokens_out, 31)
        self.assertEqual(out.usage.cached_tokens_in, 6016)

    def test_error_envelope_maps_to_provider_error(self):
        adapter = _adapter(
            runner_fn=lambda prompt: _envelope(
                text="rate limit exceeded", is_error=True))
        with self.assertRaises(ProviderError) as ctx:
            adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(ctx.exception.status_code, 429)

    def test_missing_text_result_is_a_provider_error(self):
        env = _envelope()
        env["result"] = None
        adapter = _adapter(runner_fn=lambda prompt: env)
        with self.assertRaises(ProviderError):
            adapter.decide(CASE, "choice", _ctx())

    def test_prose_around_json_still_parses(self):
        adapter = _adapter(runner_fn=lambda prompt: _envelope(
            text=f"Here is my decision.\n{GOOD_JSON}\nDone."))
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")

    def test_schema_is_rendered_into_the_prompt(self):
        # A text harness has no response_format channel: the schema
        # must travel inside the prompt text, and the repair attempt
        # must add the JSON-only instruction. If the schema render
        # were dropped, every real call would break while a fake
        # returning canned JSON would notice nothing.
        prompts = []

        def runner(prompt):
            prompts.append(prompt)
            if len(prompts) == 1:
                return _envelope(text="no structured answer here")
            return _envelope()

        adapter = _adapter(runner_fn=runner)
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        self.assertEqual(len(prompts), 2)
        for prompt in prompts:
            self.assertIn(
                "Respond with a single JSON object matching this "
                "schema", prompt)
            self.assertIn('"decision"', prompt)
        self.assertNotIn("Return ONLY the JSON object.", prompts[0])
        self.assertIn("Return ONLY the JSON object.", prompts[1])

    def test_cache_write_tokens_count_toward_total_input(self):
        env = _envelope()
        env["usage"]["cacheWriteTokens"] = 250
        adapter = _adapter(runner_fn=lambda prompt: env)
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.usage.tokens_in, 13366 + 6016 + 250)
        self.assertEqual(out.usage.cached_tokens_in, 6016)

    def test_negative_usage_is_a_provider_error(self):
        env = _envelope()
        env["usage"]["cacheWriteTokens"] = -5
        adapter = _adapter(runner_fn=lambda prompt: env)
        with self.assertRaises(ProviderError):
            adapter.decide(CASE, "choice", _ctx())

    def test_non_numeric_usage_is_a_provider_error(self):
        env = _envelope()
        env["usage"]["inputTokens"] = "lots"
        adapter = _adapter(runner_fn=lambda prompt: env)
        with self.assertRaises(ProviderError):
            adapter.decide(CASE, "choice", _ctx())

    def test_usage_not_an_object_is_a_provider_error(self):
        # A list or string usage must fail as a ProviderError, not
        # escape as an AttributeError from .get on the wrong type.
        for bad in ([1, 2], "lots", 7):
            env = _envelope()
            env["usage"] = bad
            adapter = _adapter(runner_fn=lambda prompt, e=env: e)
            with self.assertRaises(ProviderError):
                adapter.decide(CASE, "choice", _ctx())

    def test_missing_usage_object_is_a_provider_error(self):
        # No usage object at all: the call cannot be accounted, so
        # it must fail rather than seal zero usage.
        env = _envelope()
        del env["usage"]
        adapter = _adapter(runner_fn=lambda prompt: env)
        with self.assertRaises(ProviderError):
            adapter.decide(CASE, "choice", _ctx())

    def test_missing_primary_counter_is_a_provider_error(self):
        for field in ("inputTokens", "outputTokens", "cacheReadTokens"):
            env = _envelope()
            del env["usage"][field]
            adapter = _adapter(runner_fn=lambda prompt, e=env: e)
            with self.assertRaises(ProviderError):
                adapter.decide(CASE, "choice", _ctx())

    def test_missing_cache_write_counter_reads_as_zero(self):
        # The live-verified envelope does not promise this field.
        env = _envelope()
        del env["usage"]["cacheWriteTokens"]
        adapter = _adapter(runner_fn=lambda prompt: env)
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.usage.tokens_in, 13366 + 6016)

    def test_huge_usage_counter_is_a_provider_error(self):
        # A several-hundred-digit counter must fail closed here,
        # not overflow a downstream float conversion.
        env = _envelope()
        env["usage"]["inputTokens"] = 10**400
        adapter = _adapter(runner_fn=lambda prompt: env)
        with self.assertRaises(ProviderError):
            adapter.decide(CASE, "choice", _ctx())

    def test_non_object_envelope_is_a_provider_error(self):
        adapter = _adapter(runner_fn=lambda prompt: ["not", "a", "dict"])
        with self.assertRaises(ProviderError):
            adapter.decide(CASE, "choice", _ctx())

    def test_entry_point_is_registered(self):
        # The registry id must equal the adapter name, or
        # `peira run --adapter cursor-harness` cannot resolve it.
        pyproject = (
            Path(__file__).resolve().parent.parent / "pyproject.toml")
        self.assertIn(
            'cursor-harness = '
            '"peira.adapters.cursor_harness:CursorHarnessAdapter"',
            pyproject.read_text())

    def test_error_text_with_rate_substring_is_not_a_429(self):
        # "generated" and "accurate" contain "rate"; a phrase match
        # must not misclassify an ordinary agent error as throttling.
        adapter = _adapter(
            runner_fn=lambda prompt: _envelope(
                text="the model generated an accurate summary, "
                     "then the session failed",
                is_error=True))
        with self.assertRaises(ProviderError) as ctx:
            adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(ctx.exception.status_code, 502)


_STUB_SOURCE = '''\
import json
import os
import sys
import time

mode = os.environ.get("STUB_MODE", "ok")
if mode == "sleep":
    time.sleep(5)
    sys.exit(0)
if mode == "exit3":
    print("stub boom", file=sys.stderr)
    sys.exit(3)
capture = os.environ.get("STUB_CAPTURE")
if capture:
    with open(capture, "w") as fh:
        json.dump({
            "argv": sys.argv[1:],
            "key_in_argv": "crsr-test" in " ".join(sys.argv[1:]),
            "key_in_env": os.environ.get("CURSOR_API_KEY"),
        }, fh)
if mode == "nonjson":
    print("this is not json")
    sys.exit(0)
print(json.dumps({
    "type": "result", "subtype": "success", "is_error": False,
    "duration_ms": 10, "duration_api_ms": 9,
    "result": __GOOD_JSON__,
    "session_id": "sess-stub", "request_id": "req-stub",
    "usage": {"inputTokens": 100, "outputTokens": 5,
              "cacheReadTokens": 40, "cacheWriteTokens": 2},
}))
'''


class TestCursorHarnessSubprocess(unittest.TestCase):
    """The real transport, exercised through a stub agent binary.

    The runner_fn tests above never touch _subprocess_runner, so
    argv shape, env-only key delivery, and the exit/timeout/JSON
    error mappings are asserted here against a fake CLI.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        stub = Path(self._tmp.name) / "agent"
        stub.write_text(
            f"#!{sys.executable}\n" + _STUB_SOURCE.replace(
                "__GOOD_JSON__", repr(GOOD_JSON)))
        stub.chmod(0o755)
        self.stub = str(stub)
        self.capture = str(Path(self._tmp.name) / "capture.json")

    def _real_adapter(self, **over):
        kwargs = {
            "api_key": "crsr-test",
            "agent_bin": self.stub,
            "workspace": self._tmp.name,
        }
        kwargs.update(over)
        return CursorHarnessAdapter(**kwargs)

    def test_argv_shape_and_env_only_key(self):
        with _env(STUB_MODE="ok", STUB_CAPTURE=self.capture):
            out = self._real_adapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        self.assertEqual(out.usage.tokens_in, 100 + 40 + 2)
        capture = json.loads(Path(self.capture).read_text())
        argv = capture["argv"]
        self.assertEqual(argv[argv.index("--model") + 1],
                         "grok-4.7-high-fast")
        self.assertEqual(argv[argv.index("--mode") + 1], "ask")
        self.assertEqual(argv[argv.index("--output-format") + 1],
                         "json")
        self.assertFalse(capture["key_in_argv"])
        self.assertEqual(capture["key_in_env"], "crsr-test")

    def test_missing_binary_is_a_provider_error(self):
        adapter = self._real_adapter(
            agent_bin=str(Path(self._tmp.name) / "no-such-agent"))
        with self.assertRaises(ProviderError) as ctx:
            adapter.decide(CASE, "choice", _ctx())
        self.assertIn("binary not found", str(ctx.exception))

    def test_nonzero_exit_maps_to_502(self):
        with _env(STUB_MODE="exit3"):
            with self.assertRaises(ProviderError) as ctx:
                self._real_adapter().decide(CASE, "choice", _ctx())
        self.assertEqual(ctx.exception.status_code, 502)

    def test_non_json_stdout_is_a_provider_error(self):
        with _env(STUB_MODE="nonjson"):
            with self.assertRaises(ProviderError):
                self._real_adapter().decide(CASE, "choice", _ctx())

    def test_timeout_maps_to_408(self):
        with _env(STUB_MODE="sleep"):
            with self.assertRaises(ProviderError) as ctx:
                self._real_adapter(timeout_s=0.5).decide(
                    CASE, "choice", _ctx())
        self.assertEqual(ctx.exception.status_code, 408)


if __name__ == "__main__":
    unittest.main()
