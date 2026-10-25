"""Tests for the Cloudflare Clef (Workers AI) adapter.

All transport is faked: no network, no credentials, no access needed.
The fake transport receives the exact payload the adapter would POST
and returns a canned parsed Workers AI envelope, ``{"result":
{"answers": ..., "usage": ...}, "success": true, "errors": [],
"messages": []}``, written against Cloudflare's documented Clef REST
shape: the request body carries the short model name plus ``state``
and ``questions``; answers carry ``choice``/``score``/``noul`` fields
exactly as on the System One wire.
"""

import unittest

from peira.adapters.base import ProviderError, validate_output
from peira.adapters import clef as clef_mod
from peira.adapters.clef import (
    ACCOUNT_ENV,
    MODEL_ID,
    SUPPORTED_MODELS,
    TOKEN_ENV,
    ClefAdapter,
)


# B2 (D-25 amended): the adapter-visible context is an opaque per-call
# handle; no case id, no arm, no gold labels. The candidate decision
# labels come from the case input's explicit "options" list.
def _case_input(**over):
    d = {"prompt": "Decision: approve or deny?",
         "options": ["approve", "deny"]}
    d.update(over)
    return d


def _ctx(**over):
    from peira.adapters.base import CallContext
    return CallContext(call_id=over.get("call_id", "call-test"))


def _adapter(transport=None, **kw):
    kw.setdefault("account_id", "acct-test")
    kw.setdefault("api_token", "tok-test")
    if transport is not None:
        kw["transport"] = transport
    return ClefAdapter(**kw)


def _transport_for(answers, usage=None, latency=12.5, success=True,
                   result_extra=None):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        result = {"answers": answers,
                  "usage": usage or {"input_tokens": 100,
                                     "output_tokens": 0}}
        if result_extra:
            result.update(result_extra)
        return {"result": result, "success": success, "errors": [],
                "messages": [], "_latency_ms": latency}

    fake.seen = seen
    return fake


class TestClefConstruction(unittest.TestCase):
    def test_missing_account_id_is_actionable(self):
        import os
        old = os.environ.pop(ACCOUNT_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                ClefAdapter(api_token="t")
        finally:
            if old is not None:
                os.environ[ACCOUNT_ENV] = old
        self.assertIn(ACCOUNT_ENV, str(cm.exception))

    def test_missing_token_is_actionable(self):
        import os
        old = os.environ.pop(TOKEN_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                ClefAdapter(account_id="a")
        finally:
            if old is not None:
                os.environ[TOKEN_ENV] = old
        self.assertIn(TOKEN_ENV, str(cm.exception))
        self.assertIn("Workers AI scope", str(cm.exception))

    def test_explicit_credentials_ok(self):
        a = _adapter()
        self.assertEqual(a._account_id, "acct-test")
        self.assertEqual(a._api_token, "tok-test")

    def test_default_model_is_clef_flash(self):
        a = _adapter()
        self.assertEqual(a.model, "@cf/cloudflare/clef-flash")
        self.assertEqual(MODEL_ID, "@cf/cloudflare/clef-flash")

    def test_all_supported_models_construct(self):
        for model in SUPPORTED_MODELS:
            a = _adapter(model=model)
            self.assertEqual(a.model, model)
            self.assertEqual(a.version, model)
            self.assertEqual(a.cache_namespace, f"clef:{model}")
            self.assertTrue(a.api_url.endswith(f"/ai/run/{model}"))
            self.assertIn("acct-test", a.api_url)

    def test_model_rejects_short_names_and_unknown_ids(self):
        # The short names are request-body values, never adapter model
        # ids; an id that does not name the exact Workers AI model
        # would silently measure the wrong thing.
        for bad in ("clef-flash", "clef", "clef-omni",
                    "@cf/cloudflare/clef-2", "@cf/meta/llama-guard-3-8b",
                    "", "latest"):
            with self.assertRaises(ValueError, msg=bad):
                _adapter(model=bad)

    def test_model_rejection_message_matches_troubleshooting_quote(self):
        # docs/Troubleshooting.md quotes this message verbatim in its
        # heading, so the full emitted text is pinned here. A wording
        # change must move the doc quote in the same change.
        with self.assertRaises(ValueError) as cm:
            _adapter(model="clef-flash")
        self.assertEqual(
            str(cm.exception),
            "clef adapter pins model '@cf/cloudflare/clef-flash', "
            "'@cf/cloudflare/clef' or '@cf/cloudflare/clef-omni'; "
            "got 'clef-flash'. Short names and floating tags are "
            "never allowed; a measurement must name the exact model.")

    def test_version_and_cache_namespaces_differ_per_model(self):
        a = _adapter(model="@cf/cloudflare/clef-flash")
        b = _adapter(model="@cf/cloudflare/clef")
        self.assertNotEqual(a.cache_namespace, b.cache_namespace)
        self.assertNotEqual(a.api_url, b.api_url)

    def test_decide_sends_short_model_name_in_body(self):
        t = _transport_for({"decision": {"choice": "deny",
                                         "confidence": 0.9}})
        out = _adapter(transport=t, model="@cf/cloudflare/clef").decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(t.seen["payload"]["model"], "clef")
        self.assertEqual(out.usage.model, "@cf/cloudflare/clef")
        self.assertEqual(out.transcript["model"], "@cf/cloudflare/clef")


class TestClefChoice(unittest.TestCase):
    def test_choice_maps_option_and_confidence(self):
        t = _transport_for({
            "decision": {"choice": "approve",
                         "probabilities": {"deny": 0.2, "approve": 0.7,
                                           "other": 0.1},
                         "confidence": 0.7},
        })
        out = _adapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.7)
        self.assertEqual(out.usage.model, MODEL_ID)
        self.assertEqual(out.usage.tokens_in, 100)
        self.assertEqual(out.usage.tokens_out, 0)

    def test_choice_request_shape(self):
        t = _transport_for({"decision": {"choice": "deny",
                                         "confidence": 0.9}})
        _adapter(transport=t).decide(_case_input(), "choice", _ctx())
        payload = t.seen["payload"]
        self.assertEqual(payload["model"], "clef-flash")
        self.assertEqual(payload["state"], "Decision: approve or deny?")
        q = payload["questions"]["decision"]
        self.assertEqual(set(q), {"type", "instructions", "criteria"})
        self.assertEqual(q["type"], "choice")
        self.assertTrue(q["instructions"])
        self.assertIn("deny", q["criteria"])
        self.assertIn("approve", q["criteria"])

    def test_choice_labels_come_from_input_options(self):
        t = _transport_for({"decision": {"choice": "deny",
                                         "confidence": 0.9}})
        _adapter(transport=t).decide(
            _case_input(options=["deny", "approve", "hold"]),
            "choice", _ctx())
        labels = list(t.seen["payload"]["questions"]["decision"]["criteria"])
        self.assertEqual(labels, ["approve", "deny", "hold", "other"])

    def test_choice_unknown_option_is_terminal(self):
        t = _transport_for({"decision": {"choice": "maybe",
                                         "confidence": 0.5}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_unsupported_primitive(self):
        with self.assertRaises(ValueError):
            _adapter().decide(_case_input(), "bogus", _ctx())


    def test_choice_confidence_huge_int_clamps_to_extreme(self):
        # Confidence routes through the clamp helper, whose int
        # comparison is exact: a several-hundred-digit JSON integer
        # clamps to the same extreme a large finite value would
        # instead of escaping as an unclassified OverflowError.
        t = _transport_for({
            "decision": {"choice": "approve", "confidence": 10**400},
        })
        out = _adapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertEqual(out.confidence, 1.0)

class TestClefScore(unittest.TestCase):
    def _score_adapter(self, value, option="deny", conf=0.8):
        t = _transport_for({
            "score": {"score": value, "confidence": conf},
            "decision": {"choice": option, "confidence": conf},
        })
        return _adapter(transport=t), t

    def test_score_normalized_to_unit_interval(self):
        a, _ = self._score_adapter(3.2)
        out = a.decide(_case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 3.2 / 4)  # 5 levels, 0-based
        self.assertEqual(out.decision, "deny")

    def test_score_clamped(self):
        a, _ = self._score_adapter(99)
        out = a.decide(_case_input(), "score", _ctx())
        self.assertEqual(out.score, 1.0)

    def test_score_direct_huge_int_clamps_to_extreme(self):
        # The direct path clamps out-of-range scores. A several-
        # hundred-digit JSON integer parses to an int whose float()
        # raises OverflowError. Compared exactly it is out of range
        # in its own direction, so it clamps to the same extreme a
        # large finite value would instead of escaping unclassified.
        a, _ = self._score_adapter(10**400)
        out = a.decide(_case_input(), "score", _ctx())
        self.assertEqual(out.score, 1.0)
        a, _ = self._score_adapter(-(10**400))
        out = a.decide(_case_input(), "score", _ctx())
        self.assertEqual(out.score, 0.0)

    def test_score_missing_value_computed_from_probabilities(self):
        t = _transport_for({
            "score": {"probabilities": {str(i): (1.0 if i == 4 else 0.0)
                                        for i in range(5)}},
            "decision": {"choice": "approve", "confidence": 0.9},
        })
        out = _adapter(transport=t).decide(_case_input(), "score", _ctx())
        self.assertAlmostEqual(out.score, 1.0)

    def test_score_non_numeric_probabilities_is_terminal(self):
        t = _transport_for({
            "score": {"probabilities": {"0": "high", "1": 0.5}},
            "decision": {"choice": "approve", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_noncanonical_key_spellings_are_terminal(self):
        # A probability key is matched against the canonical level
        # spellings, never parsed into a level: int() accepts every
        # spelling below and would fabricate a rubric position.
        for probs in ({" 2": 1.0}, {"01": 1.0}, {"+1": 1.0}):
            t = _transport_for({
                "score": {"probabilities": probs},
                "decision": {"choice": "approve", "confidence": 0.9},
            })
            with self.assertRaises(ProviderError, msg=repr(probs)):
                _adapter(transport=t).decide(_case_input(), "score",
                                              _ctx())

    def test_score_fallback_duplicate_level_spellings_are_terminal(self):
        # "1" and "01" name the same level under int() parsing and
        # their mass sums to 1.0, so parsing double-counted level 1
        # into a fabricated score instead of failing closed.
        t = _transport_for({
            "score": {"probabilities": {"1": 0.5, "01": 0.5}},
            "decision": {"choice": "approve", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_coerced_values_are_terminal(self):
        # The old fallback coerced values with float(), so a numeric
        # string or a bool became a genuine probability. Values are
        # measurements the model reported, never values to repair.
        for probs in ({"4": "1.0"}, {"4": True}):
            t = _transport_for({
                "score": {"probabilities": probs},
                "decision": {"choice": "approve", "confidence": 0.9},
            })
            with self.assertRaises(ProviderError, msg=repr(probs)):
                _adapter(transport=t).decide(_case_input(), "score",
                                              _ctx())

    def test_score_fallback_out_of_range_key_is_terminal(self):
        # Level 99 does not exist. The old fallback computed 99 and
        # the score clamp turned it into a maximal measurement.
        t = _transport_for({
            "score": {"probabilities": {"99": 1.0}},
            "decision": {"choice": "approve", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_partial_mass_is_terminal(self):
        # The stated mass totals 0.1. The missing 0.9 is not the
        # adapter's to invent or silently ignore.
        t = _transport_for({
            "score": {"probabilities": {"4": 0.1}},
            "decision": {"choice": "approve", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_empty_probabilities_is_terminal(self):
        # An empty map is missing data, not a measured worst score:
        # the old fallback summed nothing into a score of 0.0.
        t = _transport_for({
            "score": {"probabilities": {}},
            "decision": {"choice": "approve", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_value_above_one_is_terminal(self):
        t = _transport_for({
            "score": {"probabilities": {"4": 2.0}},
            "decision": {"choice": "approve", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_sparse_full_mass_accepted(self):
        # Levels carrying no probability may be omitted. The stated
        # mass still totals 1 and the weighted position is exact.
        t = _transport_for({
            "score": {"probabilities": {"0": 0.25, "4": 0.75}},
            "decision": {"choice": "approve", "confidence": 0.9},
        })
        out = _adapter(transport=t).decide(_case_input(), "score",
                                           _ctx())
        self.assertAlmostEqual(out.score, 0.75)

    def test_score_fallback_huge_int_probability_is_terminal(self):
        # A several-hundred-digit JSON integer parses to a Python
        # int, and float() on it raises OverflowError. The fallback
        # must void it like any other out-of-range value instead of
        # letting the OverflowError escape in ProviderError's place.
        t = _transport_for({
            "score": {"probabilities": {"2": 10**400}},
            "decision": {"choice": "approve", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_sends_two_questions(self):
        a, t = self._score_adapter(3)
        a.decide(_case_input(), "score", _ctx())
        qs = t.seen["payload"]["questions"]
        self.assertEqual(set(qs), {"score", "decision"})
        sq = qs["score"]
        self.assertEqual(set(sq), {"type", "instructions", "criteria"})
        self.assertEqual(sq["type"], "score")
        self.assertEqual(len(sq["criteria"]), 5)
        self.assertTrue(all(isinstance(c, str) and c for c in sq["criteria"]))


class TestClefNoul(unittest.TestCase):
    def test_noul_yes_means_abstain(self):
        t = _transport_for({"abstain": {"abstain": 0.8}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.6)  # |2*.8-1|

    def test_noul_no_returns_other_placeholder(self):
        t = _transport_for({"abstain": {"abstain": 0.2}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "other")
        self.assertFalse(out.abstained)
        self.assertAlmostEqual(out.confidence, 0.6)

    def test_noul_request_shape(self):
        t = _transport_for({"abstain": {"abstain": 0.1}})
        _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        q = t.seen["payload"]["questions"]["abstain"]
        self.assertEqual(q["type"], "noul")
        self.assertTrue(q["instructions"])
        self.assertNotIn("criteria", q)

    def test_noul_native_field_fallback(self):
        # The wire returns the abstain probability under its own field
        # name, {'type': 'noul', 'noul': 0.73}, with no 'abstain' key.
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.73}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.46)

    def test_documented_key_wins_over_noul(self):
        t = _transport_for({"abstain": {"abstain": 0.2, "noul": 0.9}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "other")
        self.assertFalse(out.abstained)

    def test_missing_both_keys_still_terminal(self):
        t = _transport_for({"abstain": {"type": "noul"}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "abstain", _ctx())


    def test_noul_huge_int_clamps_to_extreme(self):
        # The abstain path clamps through the same helper as the
        # confidence paths: a several-hundred-digit JSON integer
        # clamps to the extreme in its own direction instead of
        # escaping as an unclassified OverflowError.
        t = _transport_for({"abstain": {"abstain": 10**400}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "abstain")
        self.assertEqual(out.confidence, 1.0)
        t = _transport_for({"abstain": {"abstain": -(10**400)}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "other")
        self.assertEqual(out.confidence, 1.0)

class TestClefEnvelope(unittest.TestCase):
    def test_success_false_is_terminal_with_errors(self):
        def fake(payload):
            return {"result": None, "success": False,
                    "errors": [{"code": 10000,
                                "message": "Authentication error"}],
                    "messages": [], "_latency_ms": 1.0}
        with self.assertRaises(ProviderError) as cm:
            _adapter(transport=fake).decide(_case_input(), "choice", _ctx())
        self.assertIn("success=false", str(cm.exception))
        self.assertIn("10000", str(cm.exception))

    def test_missing_result_is_terminal(self):
        def fake(payload):
            return {"success": True, "errors": [], "messages": [],
                    "_latency_ms": 1.0}
        with self.assertRaises(ProviderError) as cm:
            _adapter(transport=fake).decide(_case_input(), "choice", _ctx())
        self.assertIn("'result'", str(cm.exception))

    def test_missing_answers_is_terminal(self):
        def fake(payload):
            return {"result": {"usage": {"input_tokens": 5}},
                    "success": True, "errors": [], "messages": [],
                    "_latency_ms": 1.0}
        with self.assertRaises(ProviderError):
            _adapter(transport=fake).decide(_case_input(), "choice", _ctx())

    def test_missing_usage_defaults_to_zero_tokens(self):
        def fake(payload):
            return {"result": {"answers": {"decision": {
                        "choice": "deny", "confidence": 0.9}}},
                    "success": True, "errors": [], "messages": [],
                    "_latency_ms": 3.0}
        out = _adapter(transport=fake).decide(_case_input(), "choice",
                                              _ctx())
        self.assertEqual(out.usage.tokens_in, 0)
        self.assertEqual(out.usage.tokens_out, 0)
        self.assertEqual(out.usage.latency_ms, 3.0)


class TestClefQuestionValidation(unittest.TestCase):
    def test_malformed_question_is_terminal_before_send(self):
        with self.assertRaises(ProviderError):
            clef_mod._validate_questions({"bad": {"type": "choice"}})
        with self.assertRaises(ProviderError):
            clef_mod._validate_questions(
                {"bad": {"type": "bogus", "instructions": "x"}})
        clef_mod._validate_questions({
            "d": {"type": "choice", "instructions": "i",
                  "criteria": {"a": "A"}},
            "s": {"type": "score", "instructions": "i",
                  "criteria": ["low", "high"]},
            "n": {"type": "noul", "instructions": "i"},
        })


class TestClefErrors(unittest.TestCase):
    def test_raise_for_status_mapping(self):
        a = _adapter()
        for status in (401, 403, 404, 400, 422, 429, 529, 500, 503):
            with self.assertRaises(ProviderError) as cm:
                a._raise_for_status(status, None, "detail")
            self.assertEqual(cm.exception.status_code, status)

    def test_401_message_matches_troubleshooting_quote(self):
        # docs/Troubleshooting.md quotes this message verbatim in its
        # heading, so the full emitted text is pinned here.
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(401, None, "")
        self.assertEqual(
            str(cm.exception),
            "clef API error 401; check that CLOUDFLARE_API_TOKEN is "
            "valid and has the Workers AI scope for this account.")

    def test_404_message_names_the_model(self):
        a = _adapter(model="@cf/cloudflare/clef")
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(404, None, "")
        self.assertIn("@cf/cloudflare/clef", str(cm.exception))
        self.assertIn("CLOUDFLARE_ACCOUNT_ID", str(cm.exception))

    def test_429_carries_retry_after(self):
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(429, "5", "")
        self.assertEqual(cm.exception.retry_after, 5.0)

    def test_409_carries_retry_after(self):
        # 409 is in the runner's transient set, so the server's
        # Retry-After must reach the runner like any other
        # transient's. Dropping it loses the server's stated wait.
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(409, "3", "")
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.retry_after, 3.0)

    def test_transport_timeout_maps_to_408(self):
        import urllib.error
        from unittest import mock
        adapter = _adapter()
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("timed out")):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": "clef-flash"})
        # 408 is on the runner's transient-retry path (classify_exception).
        self.assertEqual(cm.exception.status_code, 408)

    def test_transcript_has_no_token_material(self):
        import json
        t = _transport_for({"decision": {"choice": "deny",
                                         "confidence": 0.9}})
        adapter = _adapter(transport=t, api_token="tok-secret-value")
        out = adapter.decide(_case_input(), "choice", _ctx())
        blob = json.dumps(out.transcript)
        self.assertNotIn("tok-secret-value", blob)
        self.assertNotIn("tok-secret-value", json.dumps(t.seen["payload"]))

    def test_unknown_keys_ignored(self):
        t = _transport_for({"decision": {"choice": "deny",
                                         "confidence": 0.9}})
        out = _adapter(transport=t).decide(_case_input(weird_key="x"),
                                          "choice", _ctx())
        self.assertEqual(out.decision, "deny")


class TestClefMalformedValues(unittest.TestCase):
    """Fail-closed behaviour for non-finite and mistyped wire values.

    Python's json accepts NaN/Infinity literals, so a malformed live
    response can carry them. Clamping NaN would silently fabricate a
    maximal measurement (min/max comparisons with NaN are false), so
    every numeric path must raise ProviderError instead.
    """

    def test_nan_confidence_is_terminal(self):
        t = _transport_for({"decision": {"choice": "deny",
                                         "confidence": float("nan")}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_inf_score_is_terminal(self):
        t = _transport_for({
            "score": {"score": float("inf")},
            "decision": {"choice": "deny", "confidence": 0.8},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_nan_abstain_is_terminal(self):
        t = _transport_for({"abstain": {"abstain": float("nan")}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "abstain", _ctx())

    def test_bool_confidence_is_terminal(self):
        # A bool is never a legitimate confidence (base._unit_interval
        # states the same rule); score and abstain values already
        # reject bools explicitly, confidence must not slip through
        # float(True) == 1.0.
        t = _transport_for({"decision": {"choice": "deny",
                                         "confidence": True}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_non_dict_probabilities_is_terminal(self):
        t = _transport_for({"decision": {"choice": "deny",
                                         "probabilities": [0.1, 0.9]}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_malformed_usage_counters_are_terminal(self):
        t = _transport_for(
            {"decision": {"choice": "deny", "confidence": 0.9}},
            usage={"input_tokens": "abc", "output_tokens": 0})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_coerced_usage_counters_are_terminal(self):
        # Counters are never coerced: a bool, a float, a numeric
        # string, a negative or an infinity is malformed wire data,
        # not a number to repair. int() would have accepted the first
        # four (and produced a negative cost for one of them).
        for bad in (True, 1.9, "12", -5, float("inf")):
            t = _transport_for(
                {"decision": {"choice": "deny", "confidence": 0.9}},
                usage={"input_tokens": bad, "output_tokens": 0})
            with self.assertRaises(ProviderError, msg=repr(bad)):
                _adapter(transport=t).decide(_case_input(), "choice",
                                              _ctx())

    def test_score_fallback_uses_level_keys_not_insertion_order(self):
        # The probability map's keys are the level indices. A map
        # delivered out of order must still weight level 4, not
        # whichever entry happens to iterate first.
        t = _transport_for({
            "score": {"probabilities": {"4": 1.0, "0": 0.0, "1": 0.0,
                                        "2": 0.0, "3": 0.0}},
            "decision": {"choice": "approve", "confidence": 0.9},
        })
        out = _adapter(transport=t).decide(_case_input(), "score", _ctx())
        self.assertAlmostEqual(out.score, 1.0)

    def test_noul_exactly_half_abstains(self):
        # Boundary: p >= 0.5 is an abstention. Per base.py's contract
        # a deliberate abstain decision is decision="abstain" with
        # abstained=False (abstained=True means no usable decision was
        # produced at all); the Jev adapter returns exactly this.
        t = _transport_for({"abstain": {"abstain": 0.5}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "abstain")
        self.assertFalse(out.abstained)
        self.assertAlmostEqual(out.confidence, 0.0)

    def test_408_carries_retry_after(self):
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(408, "7", "")
        self.assertEqual(cm.exception.status_code, 408)
        self.assertEqual(cm.exception.retry_after, 7.0)



class TestRetryAfterNonfinite(unittest.TestCase):
    def test_retry_after_nonfinite_is_dropped(self):
        # "inf" and "nan" parse as floats; neither is a usable
        # delay. Finite values pass through (the runner caps the
        # delay at MAX_RETRY_AFTER_S when it consumes the value).
        self.assertIsNone(clef_mod._parse_retry_after("inf"))
        self.assertIsNone(clef_mod._parse_retry_after("nan"))
        self.assertIsNone(clef_mod._parse_retry_after("1e400"))
        self.assertEqual(clef_mod._parse_retry_after("7"), 7.0)


class TestClefClampStringGate(unittest.TestCase):
    def test_clamp_rejects_string_values(self):
        # Only genuine numbers reach the clamp conversion: a string
        # the wire sent is drift, never something to coerce into a
        # measurement.
        with self.assertRaises(ProviderError):
            clef_mod._clamp01("0.9", "confidence")

if __name__ == "__main__":
    unittest.main()
