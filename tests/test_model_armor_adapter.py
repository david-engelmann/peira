"""Tests for the Google Cloud Model Armor adapter.

All transport is faked: no network, no GCP project, no access token
needed. The fake transport receives the exact payload the adapter
would POST and returns a canned parsed response.

The fakes below are written against the documented Model Armor REST
wire shape — ``{"userPromptData": {"text": ...}}`` in requests,
``sanitizationResult.filterMatchState`` (``MATCH_FOUND`` /
``NO_MATCH_FOUND``) in responses — not against any earlier draft of
this adapter.
"""

import os
import unittest
from unittest import mock

from peira.adapters.base import ProviderError, validate_output
from peira.adapters.model_armor import (
    DEFAULT_LOCATION,
    LOCATION_ENV,
    PROJECT_ENV,
    TEMPLATE_ENV,
    TOKEN_ENV,
    ModelArmorAdapter,
    _api_url,
)


def _case_input(**over):
    d = {"prompt": "Decision: approve or deny?",
         "options": ["approve", "deny"]}
    d.update(over)
    return d


def _ctx(**over):
    from peira.adapters.base import CallContext
    return CallContext(call_id=over.get("call_id", "call-test"))


def _adapter(transport):
    return ModelArmorAdapter(project_id="proj-1", template_id="tmpl-1",
                             access_token="tok", transport=transport)


def _response(match=False, match_state=None, latency=12.5,
              filter_results=None):
    state = match_state or ("MATCH_FOUND" if match else "NO_MATCH_FOUND")
    fr = filter_results or {"piAndJailbreakFilter": {
        "piAndJailbreakFilterResult": {"matchState": state}}}
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        return {
            "sanitizationResult": {
                "invocationResult": "SUCCESS",
                "filterMatchState": state,
                "filterResults": fr,
            },
            "_latency_ms": latency,
        }

    fake.seen = seen
    return fake


class TestModelArmorConstruction(unittest.TestCase):
    def test_missing_project_is_actionable(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as cm:
                ModelArmorAdapter(template_id="t", access_token="tok")
        self.assertIn(PROJECT_ENV, str(cm.exception))

    def test_missing_template_is_actionable(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as cm:
                ModelArmorAdapter(project_id="p", access_token="tok")
        self.assertIn(TEMPLATE_ENV, str(cm.exception))

    def test_missing_token_is_actionable(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as cm:
                ModelArmorAdapter(project_id="p", template_id="t")
        self.assertIn(TOKEN_ENV, str(cm.exception))

    def test_missing_token_suggests_gcloud(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as cm:
                ModelArmorAdapter(project_id="p", template_id="t")
        self.assertIn("gcloud", str(cm.exception))

    def test_missing_hint_names_real_kwarg(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as cm:
                ModelArmorAdapter(template_id="t", access_token="tok")
        # The hint must name the real constructor kwarg, not the env var
        # lowercased.
        self.assertIn("(or pass project_id=...)", str(cm.exception))

    def test_explicit_config_ok(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            a = _adapter(_response())
        self.assertEqual(a._project_id, "proj-1")
        self.assertEqual(a._location, DEFAULT_LOCATION)
        self.assertEqual(a._template_id, "tmpl-1")
        self.assertEqual(a._access_token, "tok")

    def test_location_override(self):
        a = ModelArmorAdapter(project_id="p", location="europe-west1",
                              template_id="t", access_token="tok",
                              transport=_response())
        self.assertEqual(a._location, "europe-west1")
        self.assertIn("europe-west1", a.api_url)

    def test_location_from_env(self):
        with mock.patch.dict(os.environ, {LOCATION_ENV: "asia-northeast1"},
                             clear=True):
            a = ModelArmorAdapter(project_id="p", template_id="t",
                                  access_token="tok", transport=_response())
        self.assertEqual(a._location, "asia-northeast1")

    def test_env_vars_declared(self):
        self.assertEqual(ModelArmorAdapter._env_vars,
                         (PROJECT_ENV, LOCATION_ENV, TEMPLATE_ENV, TOKEN_ENV))

    def test_endpoint_pinned(self):
        url = _api_url("p", "us-central1", "t")
        self.assertEqual(
            url,
            "https://modelarmor.us-central1.rep.googleapis.com/v1/"
            "projects/p/locations/us-central1/templates/t:"
            "sanitizeUserPrompt")
        a = ModelArmorAdapter(project_id="p", template_id="t",
                              access_token="tok", transport=_response())
        self.assertEqual(a.api_url, _api_url("p", "us-central1", "t"))

    def test_cache_namespace_pinned(self):
        self.assertEqual(ModelArmorAdapter.cache_namespace, "model-armor")

    def test_abstain_only(self):
        self.assertEqual(ModelArmorAdapter.supported_primitives,
                         frozenset({"abstain"}))

    def test_unsupported_primitive_rejected(self):
        a = _adapter(_response())
        with self.assertRaises(ValueError):
            a.decide(_case_input(), "choice", _ctx())

    def test_name_and_version(self):
        self.assertEqual(ModelArmorAdapter.name, "model-armor")
        self.assertEqual(ModelArmorAdapter.version, "1.0")


class TestModelArmorDecide(unittest.TestCase):
    def test_match_abstains(self):
        fake = _response(match=True)
        a = _adapter(fake)
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertFalse(out.abstained)
        self.assertEqual(out.confidence, 1.0)

    def test_no_match_is_other(self):
        fake = _response(match=False)
        a = _adapter(fake)
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "other")
        self.assertFalse(out.abstained)

    def test_payload_shape(self):
        fake = _response()
        a = _adapter(fake)
        a.decide(_case_input(prompt="screen me"), "abstain", _ctx())
        self.assertEqual(fake.seen["payload"],
                         {"userPromptData": {"text": "screen me"}})

    def test_matched_filter_names_recorded(self):
        fr = {"piAndJailbreakFilter": {
            "piAndJailbreakFilterResult": {"matchState": "MATCH_FOUND"}},
              "csamFilter": {"csamFilterResult":
                             {"matchState": "NO_MATCH_FOUND"}}}
        a = _adapter(_response(match=True, filter_results=fr))
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.transcript["matched_filters"],
                         ["piAndJailbreakFilter"])

    def test_matched_filter_names_doubly_nested(self):
        # SDP nests matchState two levels deep; the walk must find it.
        fr = {"sdpFilter": {"sdpFilterResult": {
            "inspectResult": {"matchState": "MATCH_FOUND"}}}}
        a = _adapter(_response(match=True, filter_results=fr))
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.transcript["matched_filters"], ["sdpFilter"])

    def test_empty_input_short_circuits(self):
        calls = []

        def fake(payload):
            calls.append(payload)
            raise AssertionError("should not be called")

        a = _adapter(fake)
        out = a.decide(_case_input(prompt="   "), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(calls, [])
        self.assertEqual(out.decision, "other")
        self.assertEqual(out.usage.cost_usd, 0.0)
        self.assertNotEqual(out.usage.model, "gcp:model-armor")
        self.assertEqual(out.transcript["scores"]["p_malicious"], 0.0)

    def test_missing_result_raises(self):
        def fake(payload):
            return {"_latency_ms": 1.0}

        a = _adapter(fake)
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "abstain", _ctx())

    def test_unexpected_match_state_raises(self):
        a = _adapter(_response(match_state="SOME_NEW_STATE"))
        with self.assertRaises(ProviderError) as cm:
            a.decide(_case_input(), "abstain", _ctx())
        self.assertIn("filterMatchState", str(cm.exception))

    def test_usage_model_pinned(self):
        a = _adapter(_response())
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.usage.model, "gcp:model-armor")
        self.assertEqual(out.usage.latency_ms, 12.5)
        self.assertEqual(out.transcript["model"], "gcp:model-armor")

    def test_template_resource_name_in_transcript(self):
        a = _adapter(_response())
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.transcript["template"],
                         "projects/proj-1/locations/us-central1/"
                         "templates/tmpl-1")


class TestModelArmorErrorMapping(unittest.TestCase):
    def test_401_terminal(self):
        with self.assertRaises(ProviderError) as cm:
            ModelArmorAdapter._raise_for_status(401, None, "invalid_token")
        self.assertEqual(cm.exception.status_code, 401)
        self.assertIn(TOKEN_ENV, str(cm.exception))

    def test_429_transient_with_retry_after(self):
        with self.assertRaises(ProviderError) as cm:
            ModelArmorAdapter._raise_for_status(429, "7", "slow down")
        self.assertEqual(cm.exception.status_code, 429)
        self.assertEqual(cm.exception.retry_after, 7.0)

    def test_500_transient(self):
        with self.assertRaises(ProviderError) as cm:
            ModelArmorAdapter._raise_for_status(500, None, "oops")
        self.assertEqual(cm.exception.status_code, 500)
        self.assertIsNone(cm.exception.retry_after)

    def test_404_points_at_template_config(self):
        with self.assertRaises(ProviderError) as cm:
            ModelArmorAdapter._raise_for_status(404, None, "not found")
        self.assertEqual(cm.exception.status_code, 404)
        self.assertIn(TEMPLATE_ENV, str(cm.exception))

    def test_400_terminal(self):
        with self.assertRaises(ProviderError) as cm:
            ModelArmorAdapter._raise_for_status(400, None, "bad request")
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIsNone(cm.exception.retry_after)


if __name__ == "__main__":
    unittest.main()
