"""Tests for the Perplexity pplx-decider (Decisions API) adapter.

All transport is faked: no network, no credentials, no access needed.
The fake transport receives the exact payload the adapter would POST
and returns a canned parsed response body written against the wire
shape observed live on 2026-10-15: the body is NOT enveloped, the top
level carries ``answers`` keyed by question name, a ``model`` echo of
the id sent, and ``usage`` with integer counters; answers carry
``choice``/``score``/``noul`` fields plus a ``type`` echo, exactly as
on the System One wire.
"""

import unittest

from peira.adapters.base import ProviderError, validate_output
from peira.adapters import pplx_decider as pplx_mod
from peira.adapters.pplx_decider import (
    API_KEY_ENV,
    API_URL,
    MODEL_ID,
    SUPPORTED_MODEL_IDS,
    PplxDeciderAdapter,
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
    kw.setdefault("api_key", "tok-test")
    if transport is not None:
        kw["transport"] = transport
    return PplxDeciderAdapter(**kw)


def _transport_for(answers, usage=None, latency=12.5, model=MODEL_ID):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        body = {"answers": answers,
                "usage": usage or {"input_tokens": 100,
                                   "output_tokens": 3},
                "_latency_ms": latency}
        if model is not None:
            body["model"] = model
        return body

    fake.seen = seen
    return fake


class TestPplxConstruction(unittest.TestCase):
    def test_missing_api_key_is_actionable(self):
        import os
        old = os.environ.pop(API_KEY_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                PplxDeciderAdapter()
        finally:
            if old is not None:
                os.environ[API_KEY_ENV] = old
        self.assertIn(API_KEY_ENV, str(cm.exception))
        self.assertIn("Perplexity API key", str(cm.exception))

    def test_explicit_api_key_ok(self):
        a = _adapter()
        self.assertEqual(a._api_token, "tok-test")

    def test_default_model_is_v11(self):
        a = _adapter()
        self.assertEqual(a.model, "pplx-decider-v1.1-27b")
        self.assertEqual(MODEL_ID, "pplx-decider-v1.1-27b")

    def test_all_supported_models_construct(self):
        for model in SUPPORTED_MODEL_IDS:
            a = _adapter(model=model)
            self.assertEqual(a.model, model)
            self.assertEqual(a.version, model)
            self.assertEqual(a.cache_namespace, f"pplx-decider:{model}")
            self.assertEqual(a.api_url, API_URL)

    def test_model_rejects_unversioned_and_unknown_ids(self):
        # An id that does not name the exact served weights would
        # silently measure the wrong thing; "pplx-decider" alone is
        # the family name, never a pin.
        for bad in ("pplx-decider", "pplx-decider-v1.1", "v1.1-27b",
                    "pplx-decider-v2-27b", "pplx-decider-v1.2-27b",
                    "", "latest"):
            with self.assertRaises(ValueError, msg=bad):
                _adapter(model=bad)

    def test_model_rejection_message_matches_troubleshooting_quote(self):
        # docs/Troubleshooting.md quotes this message verbatim in its
        # heading, so the full emitted text is pinned here. A wording
        # change must move the doc quote in the same change.
        with self.assertRaises(ValueError) as cm:
            _adapter(model="pplx-decider")
        self.assertEqual(
            str(cm.exception),
            "pplx-decider adapter pins model 'pplx-decider-v1-27b' "
            "or 'pplx-decider-v1.1-27b'; got 'pplx-decider'. Floating "
            "tags and unversioned names are never allowed; a "
            "measurement must name the exact model.")

    def test_version_and_cache_namespaces_differ_per_model(self):
        a = _adapter(model="pplx-decider-v1.1-27b")
        b = _adapter(model="pplx-decider-v1-27b")
        self.assertNotEqual(a.cache_namespace, b.cache_namespace)

    def test_decide_sends_full_model_id_in_body(self):
        # Unlike the Clef wire there is no short body name: the
        # request body carries the pinned id itself (probe-verified).
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}},
                           model="pplx-decider-v1-27b")
        out = _adapter(transport=t, model="pplx-decider-v1-27b").decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(t.seen["payload"]["model"],
                         "pplx-decider-v1-27b")
        self.assertEqual(out.usage.model, "pplx-decider-v1-27b")
        self.assertEqual(out.transcript["model"], "pplx-decider-v1-27b")


class TestPplxChoice(unittest.TestCase):
    def test_choice_maps_option_and_confidence(self):
        t = _transport_for({
            "decision": {"type": "choice", "choice": "approve",
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
        self.assertEqual(out.usage.tokens_out, 3)

    def test_choice_confidence_field_wins_over_probability(self):
        # The live wire's confidence is close to but NOT equal to
        # probabilities[choice] (probe: 0.99816 vs 0.99877). The
        # adapter reports the API's confidence field.
        t = _transport_for({
            "decision": {"type": "choice", "choice": "approve",
                         "probabilities": {"approve": 0.99877,
                                           "deny": 0.00057,
                                           "other": 0.00066},
                         "confidence": 0.99816},
        })
        out = _adapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertAlmostEqual(out.confidence, 0.99816)

    def test_choice_request_shape(self):
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}})
        _adapter(transport=t).decide(_case_input(), "choice", _ctx())
        payload = t.seen["payload"]
        self.assertEqual(payload["model"], "pplx-decider-v1.1-27b")
        self.assertEqual(payload["state"], "Decision: approve or deny?")
        q = payload["questions"]["decision"]
        self.assertEqual(set(q), {"type", "instructions", "criteria"})
        self.assertEqual(q["type"], "choice")
        self.assertTrue(q["instructions"])
        self.assertIn("deny", q["criteria"])
        self.assertIn("approve", q["criteria"])

    def test_choice_labels_come_from_input_options(self):
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}})
        _adapter(transport=t).decide(
            _case_input(options=["deny", "approve", "hold"]),
            "choice", _ctx())
        labels = list(t.seen["payload"]["questions"]["decision"]["criteria"])
        self.assertEqual(labels, ["approve", "deny", "hold", "other"])

    def test_choice_unknown_option_is_terminal(self):
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "maybe",
                                         "confidence": 0.5}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_unsupported_primitive(self):
        with self.assertRaises(ValueError):
            _adapter().decide(_case_input(), "bogus", _ctx())


class TestPplxScore(unittest.TestCase):
    def _score_adapter(self, value, option="deny", conf=0.8):
        t = _transport_for({
            "score": {"type": "score", "score": value, "confidence": conf},
            "decision": {"type": "choice", "choice": option,
                         "confidence": conf},
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

    def test_score_missing_value_computed_from_probabilities(self):
        t = _transport_for({
            "score": {"type": "score",
                      "probabilities": {str(i): (1.0 if i == 4 else 0.0)
                                        for i in range(5)}},
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 0.9},
        })
        out = _adapter(transport=t).decide(_case_input(), "score", _ctx())
        self.assertAlmostEqual(out.score, 1.0)

    def test_score_bool_probability_is_terminal(self):
        # The score fallback must not let float(True) == 1.0 turn a
        # bool into a fabricated rubric position (red-team finding,
        # 2026-10-15). Bools are rejected everywhere else this
        # adapter reads a probability.
        t = _transport_for({
            "score": {"type": "score",
                      "probabilities": {"0": 0.0, "1": 0.0, "2": True,
                                        "3": 0.0, "4": 0.0}},
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_non_numeric_probabilities_is_terminal(self):
        t = _transport_for({
            "score": {"type": "score",
                      "probabilities": {"0": "high", "1": 0.5}},
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 0.9},
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

    def test_score_full_live_shape(self):
        # The probe's actual score answer shape, legend included.
        t = _transport_for({
            "score": {"type": "score", "score": 3.9069,
                      "confidence": 0.9535,
                      "legend": {str(i): lvl for i, lvl in enumerate([
                          "clearly the wrong decision",
                          "probably the wrong decision",
                          "uncertain — could go either way",
                          "probably the right decision",
                          "clearly the right decision"])},
                      "probabilities": {"0": 0.0041, "1": 0.0032,
                                        "2": 0.0063, "3": 0.0543,
                                        "4": 0.9321}},
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 0.9982},
        })
        out = _adapter(transport=t).decide(_case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 3.9069 / 4)
        self.assertEqual(out.decision, "approve")


class TestPplxNoul(unittest.TestCase):
    def test_noul_yes_means_abstain(self):
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.8}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.6)  # |2*.8-1|

    def test_noul_no_returns_other_placeholder(self):
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.2}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "other")
        self.assertFalse(out.abstained)
        self.assertAlmostEqual(out.confidence, 0.6)

    def test_noul_request_shape(self):
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.1}})
        _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        q = t.seen["payload"]["questions"]["abstain"]
        self.assertEqual(q["type"], "noul")
        self.assertTrue(q["instructions"])
        self.assertNotIn("criteria", q)

    def test_agreeing_abstain_and_noul_keys_accepted(self):
        # The Jev-documented "abstain" key is an accepted alias for
        # the verified "noul" key when both carry the same value.
        t = _transport_for({"abstain": {"type": "noul", "abstain": 0.2,
                                        "noul": 0.2}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "other")
        self.assertFalse(out.abstained)

    def test_disagreeing_abstain_keys_are_terminal(self):
        # If the API ever adds an "abstain" key that disagrees with
        # the verified "noul" value, no preference order can say which
        # is the probability. The adapter fails closed (red-team
        # finding, 2026-10-15).
        t = _transport_for({"abstain": {"type": "noul", "abstain": 0.2,
                                        "noul": 0.9}})
        with self.assertRaises(ProviderError) as cm:
            _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertIn("ambiguous", str(cm.exception))

    def test_missing_both_keys_still_terminal(self):
        t = _transport_for({"abstain": {"type": "noul"}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "abstain", _ctx())


class TestPplxResponseValidation(unittest.TestCase):
    def test_missing_answers_is_terminal(self):
        def fake(payload):
            return {"model": MODEL_ID,
                    "usage": {"input_tokens": 5, "output_tokens": 3},
                    "_latency_ms": 1.0}
        with self.assertRaises(ProviderError) as cm:
            _adapter(transport=fake).decide(_case_input(), "choice", _ctx())
        self.assertIn("'answers'", str(cm.exception))

    def test_model_echo_mismatch_is_terminal(self):
        # The response names the weights that actually ran; a
        # different echo means this pin did not produce the answers.
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}},
                           model="pplx-decider-v1-27b")
        with self.assertRaises(ProviderError) as cm:
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertIn("pplx-decider-v1-27b", str(cm.exception))
        self.assertIn("pplx-decider-v1.1-27b", str(cm.exception))

    def test_model_echo_missing_is_terminal(self):
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}},
                           model=None)
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_missing_usage_defaults_to_zero_tokens(self):
        def fake(payload):
            return {"answers": {"decision": {"type": "choice",
                                             "choice": "deny",
                                             "confidence": 0.9}},
                    "model": MODEL_ID, "_latency_ms": 3.0}
        out = _adapter(transport=fake).decide(_case_input(), "choice",
                                              _ctx())
        self.assertEqual(out.usage.tokens_in, 0)
        self.assertEqual(out.usage.tokens_out, 0)
        self.assertEqual(out.usage.latency_ms, 3.0)


class TestPplxQuestionValidation(unittest.TestCase):
    def test_malformed_question_is_terminal_before_send(self):
        with self.assertRaises(ProviderError):
            pplx_mod._validate_questions({"bad": {"type": "choice"}})
        with self.assertRaises(ProviderError):
            pplx_mod._validate_questions(
                {"bad": {"type": "bogus", "instructions": "x"}})
        pplx_mod._validate_questions({
            "d": {"type": "choice", "instructions": "i",
                  "criteria": {"a": "A"}},
            "s": {"type": "score", "instructions": "i",
                  "criteria": ["low", "high"]},
            "n": {"type": "noul", "instructions": "i"},
        })


class TestPplxErrors(unittest.TestCase):
    def test_raise_for_status_mapping(self):
        a = _adapter()
        for status in (401, 402, 403, 404, 400, 422, 429, 529, 500, 503):
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
            "pplx-decider API error 401; check that "
            "PERPLEXITY_API_KEY is valid and active, and sent as a "
            "Bearer token.")

    def test_402_message_matches_troubleshooting_quote(self):
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(402, None, "")
        self.assertEqual(
            str(cm.exception),
            "pplx-decider API error 402; the account is out of API "
            "credit; add credit in the API Console under Billing, "
            "then rerun.")

    def test_429_carries_retry_after(self):
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(429, "5", "")
        self.assertEqual(cm.exception.retry_after, 5.0)

    def test_error_detail_reads_api_error_message(self):
        # The Decisions API error body is {"error": {"message": ...,
        # "type": ...}}; the adapter surfaces the message as detail
        # and never branches on error.code.
        import io
        import json as _json
        import urllib.error
        body = _json.dumps({"error": {
            "message": "Invalid model specified",
            "type": "invalid_request_error", "code": 400}}).encode()
        err = urllib.error.HTTPError(
            API_URL, 400, "Bad Request", {}, io.BytesIO(body))
        self.assertEqual(pplx_mod._read_error_detail(err),
                         "Invalid model specified")

    def test_error_detail_falls_back_for_non_json_body(self):
        # A 504 can return an HTML page; the raw prefix is the detail.
        import io
        import urllib.error
        err = urllib.error.HTTPError(
            API_URL, 504, "Gateway Timeout", {},
            io.BytesIO(b"<html>gateway timeout</html>"))
        self.assertEqual(pplx_mod._read_error_detail(err),
                         "<html>gateway timeout</html>")

    def test_http_error_message_includes_api_detail(self):
        import io
        import json as _json
        import urllib.error
        from unittest import mock
        body = _json.dumps({"error": {
            "message": "Invalid model specified",
            "type": "invalid_request_error"}}).encode()
        err = urllib.error.HTTPError(
            API_URL, 400, "Bad Request", {}, io.BytesIO(body))
        adapter = _adapter()
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
        self.assertIn("Invalid model specified", str(cm.exception))
        self.assertEqual(cm.exception.status_code, 400)

    def test_http_error_without_headers_still_maps_status(self):
        # urllib can construct an HTTPError with headers=None; the
        # transport path must not die with AttributeError before it
        # can classify the status (red-team nit, 2026-10-15).
        import io
        import urllib.error
        from unittest import mock
        err = urllib.error.HTTPError(
            API_URL, 503, "Service Unavailable", None,
            io.BytesIO(b"upstream down"))
        adapter = _adapter()
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
        self.assertEqual(cm.exception.status_code, 503)

    def test_transport_timeout_maps_to_408(self):
        import urllib.error
        from unittest import mock
        adapter = _adapter()
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("timed out")):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
        # 408 is on the runner's transient-retry path (classify_exception).
        self.assertEqual(cm.exception.status_code, 408)

    def test_transcript_has_no_key_material(self):
        import json
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}})
        adapter = _adapter(transport=t, api_key="keymaterial-xyz")
        out = adapter.decide(_case_input(), "choice", _ctx())
        blob = json.dumps(out.transcript)
        self.assertNotIn("keymaterial-xyz", blob)
        self.assertNotIn("keymaterial-xyz", json.dumps(t.seen["payload"]))

    def test_unknown_keys_ignored(self):
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}})
        out = _adapter(transport=t).decide(_case_input(weird_key="x"),
                                           "choice", _ctx())
        self.assertEqual(out.decision, "deny")


class TestPplxMalformedValues(unittest.TestCase):
    """Fail-closed behaviour for non-finite and mistyped wire values.

    Python's json accepts NaN/Infinity literals, so a malformed live
    response can carry them. Clamping NaN would silently fabricate a
    maximal measurement (min/max comparisons with NaN are false), so
    every numeric path must raise ProviderError instead.
    """

    def test_nan_confidence_is_terminal(self):
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": float("nan")}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_inf_score_is_terminal(self):
        t = _transport_for({
            "score": {"type": "score", "score": float("inf")},
            "decision": {"type": "choice", "choice": "deny",
                         "confidence": 0.8},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_nan_abstain_is_terminal(self):
        t = _transport_for({"abstain": {"type": "noul",
                                        "noul": float("nan")}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "abstain", _ctx())

    def test_bool_confidence_is_terminal(self):
        # A bool is never a legitimate confidence (base._unit_interval
        # states the same rule); score and abstain values already
        # reject bools explicitly, confidence must not slip through
        # float(True) == 1.0.
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": True}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_non_dict_probabilities_is_terminal(self):
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "probabilities": [0.1, 0.9]}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_malformed_usage_counters_are_terminal(self):
        t = _transport_for(
            {"decision": {"type": "choice", "choice": "deny",
                          "confidence": 0.9}},
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
                {"decision": {"type": "choice", "choice": "deny",
                              "confidence": 0.9}},
                usage={"input_tokens": bad, "output_tokens": 0})
            with self.assertRaises(ProviderError, msg=repr(bad)):
                _adapter(transport=t).decide(_case_input(), "choice",
                                              _ctx())

    def test_score_fallback_uses_level_keys_not_insertion_order(self):
        # The probability map's keys are the level indices. A map
        # delivered out of order must still weight level 4, not
        # whichever entry happens to iterate first.
        t = _transport_for({
            "score": {"type": "score",
                      "probabilities": {"4": 1.0, "0": 0.0, "1": 0.0,
                                        "2": 0.0, "3": 0.0}},
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 0.9},
        })
        out = _adapter(transport=t).decide(_case_input(), "score", _ctx())
        self.assertAlmostEqual(out.score, 1.0)

    def test_noul_exactly_half_abstains(self):
        # Boundary: p >= 0.5 is an abstention. Per base.py's contract
        # a deliberate abstain decision is decision="abstain" with
        # abstained=False (abstained=True means no usable decision was
        # produced at all); the Jev adapter returns exactly this.
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.5}})
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


if __name__ == "__main__":
    unittest.main()
