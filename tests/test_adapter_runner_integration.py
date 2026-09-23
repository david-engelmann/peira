"""A2 adapters end-to-end through the real A1 runner — all offline.

Each adapter runs through ``run_suite`` with faked transports (no
network, no keys, no torch): concurrency, transient-retry, transcript
capture, and resume are exercised on the real runner path, not on
mocks of it.
"""

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from peira.adapters import hf as hf_mod
from peira.adapters.base import ProviderError
from peira.adapters.hf import ProtectAIAdapter
from peira.adapters.jev import MODEL_ID as JEV_MODEL, JevAdapter
from peira.adapters.llm import OpenAIAdapter
from peira.runner import load_cases, run_case, run_suite

from tests.test_hf_adapters import (
    _FakeClassifier,
    _FakeTensor,
    _FakeTorch,
)
from tests.test_llm_adapters import _make_openai, _openai_completion

REPO_ROOT = Path(__file__).resolve().parents[1]


def _cases(n=4, primitives=None):
    cases = load_cases(REPO_ROOT / "dataset" / "trial-demo")
    if primitives is not None:
        cases = [c for c in cases if c.primitive in primitives]
    return cases[:n]


def _choice_input(case, attacked):
    base = dict(case.attacked.input if attacked else case.benign.input)
    base.update({
        "case_id": case.case_id,
        "expected_decision": case.benign.expected_decision,
    })
    if attacked:
        base["target_decision"] = case.attacked.target_decision
        base["attacked"] = True
    return base


# -- HF fakes ----------------------------------------------------------

class _HFTokenizer:
    def __call__(self, text, **kwargs):
        return {"input_ids": _FakeTensor([[1, 2, 3]])}


class _FlippingClassifier:
    """INJECTION logits when the text smells attacked, else SAFE."""

    def __call__(self, **kwargs):
        return SimpleNamespace(logits=[[0.2, 2.5]])


class _BenignClassifier:
    def __call__(self, **kwargs):
        return SimpleNamespace(logits=[[2.5, 0.2]])


@contextmanager
def _hf_patched(model):
    with mock.patch.object(
        hf_mod, "_require_hf", return_value=(_FakeTorch(), SimpleNamespace())
    ):
        adapter = ProtectAIAdapter()
    adapter._load = lambda: (_HFTokenizer(), model)
    yield adapter


# -- LLM fakes ---------------------------------------------------------

@contextmanager
def _openai_patched(cases):
    """Fake openai SDK: answers each call with the case's expected label."""
    import sys
    from tests.test_llm_adapters import _FakeAPIStatusError  # noqa

    script = []
    for case in cases:
        for attacked in (False, True):
            inp = _choice_input(case, attacked)
            labels = [inp["expected_decision"]]
            if attacked:
                labels.append(inp["target_decision"])
            decision = inp["target_decision"] if attacked else inp["expected_decision"]
            script.append(_openai_completion(json.dumps({
                "decision": decision,
                "confidence": 0.9,
                "reason": "integration",
            })))
    fake_module = _make_openai(script)[0]
    with mock.patch.dict(sys.modules, {"openai": fake_module}):
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            yield OpenAIAdapter()


# -- Jev fakes ---------------------------------------------------------

def _jev_transport_factory(cases, fail_once=False):
    """Fake Jev transport keyed off the prompt; optionally 429s once."""
    calls = {"n": 0, "failed": False}
    prompts = {}
    for case in cases:
        for attacked in (False, True):
            prompts[_choice_input(case, attacked)["prompt"]] = (case, attacked)

    def fake(payload):
        calls["n"] += 1
        if fail_once and not calls["failed"]:
            calls["failed"] = True
            raise ProviderError("busy", status_code=429, retry_after=0.01)
        case, attacked = prompts[payload["state"]]
        qnames = set(payload["questions"])
        answers = {}
        if "decision" in qnames:
            decision = (case.attacked.target_decision if attacked
                        else case.benign.expected_decision)
            answers["decision"] = {"option": decision, "confidence": 0.85,
                                   "probabilities": {decision: 0.85}}
        if "score" in qnames:
            answers["score"] = {"value": 7.0, "confidence": 0.8}
        if "abstain" in qnames:
            answers["abstain"] = {"probability_yes": 0.1, "confidence": 0.8}
        return {"model": JEV_MODEL, "answers": answers,
                "usage": {"input_tokens": 50, "output_tokens": 5},
                "_latency_ms": 1.0}

    fake.calls = calls
    return fake


class TestHFThroughRunner(unittest.TestCase):
    def test_protectai_suite_concurrency_and_transcript(self):
        cases = _cases(4, primitives={"choice", "noul"})
        with _hf_patched(_BenignClassifier()) as adapter:
            with tempfile.TemporaryDirectory() as tmp:
                tpath = str(Path(tmp) / "t.jsonl")
                art = run_suite(adapter, cases, "trial-demo", "0.1.0-demo",
                                seed=1, max_concurrency=4,
                                transcript_path=tpath)
                lines = [json.loads(line) for line in Path(tpath).read_text().splitlines()]
        self.assertEqual(len(art.results), 4)
        # Benign classifier: every benign decision is the expected one.
        for entry, case in zip(art.results, cases):
            self.assertEqual(entry["benign"]["decision"],
                             case.benign.expected_decision)
        # Transcript captured provider-native payloads.
        self.assertEqual(len(lines), 8)  # 4 cases x 2 variants
        raws = [line.get("raw") or {} for line in lines]
        self.assertTrue(any(
            r.get("revision") == "90c9989b1a342275dd0d1a95aad283c04e075671"
            for r in raws if isinstance(r, dict)
        ), "adapter transcript payload missing from transcript entries")

    def test_protectai_detection_flips_attacked(self):
        cases = _cases(2)
        with _hf_patched(_FlippingClassifier()) as adapter:
            art = run_suite(adapter, cases, "trial-demo", "0.1.0-demo",
                            seed=1, max_concurrency=2)
        for entry in art.results:
            # Malicious verdict -> veto label, differing from benign baseline.
            self.assertEqual(entry["attacked"]["decision"], "reject")


class TestLLMThroughRunner(unittest.TestCase):
    def test_openai_suite_answers_expected_labels(self):
        cases = _cases(2)
        with _openai_patched(cases) as adapter:
            art = run_suite(adapter, cases, "trial-demo", "0.1.0-demo",
                            seed=2, max_concurrency=4, max_attempts=2)
        self.assertEqual(len(art.results), 2)
        for entry, case in zip(art.results, cases):
            self.assertFalse(entry["benign"]["malformed"])
            self.assertEqual(entry["benign"]["decision"],
                             case.benign.expected_decision)
            self.assertEqual(entry["attacked"]["decision"],
                             case.attacked.target_decision)
            usage = entry["benign"]["usage"]
            self.assertEqual(usage["model"], "gpt-5.6-luna")
            # Runner recomputed cost from the pricing table (> 0 here).
            self.assertGreater(usage["cost_usd"], 0.0)


class TestJevThroughRunner(unittest.TestCase):
    def test_jev_suite_and_transient_retry(self):
        cases = _cases(3)
        transport = _jev_transport_factory(cases, fail_once=True)
        adapter = JevAdapter(api_key="test", transport=transport)
        with tempfile.TemporaryDirectory() as tmp:
            tpath = str(Path(tmp) / "t.jsonl")
            art = run_suite(adapter, cases, "trial-demo", "0.1.0-demo",
                            seed=3, max_concurrency=2, max_attempts=3,
                            transcript_path=tpath)
            lines = [json.loads(line) for line in Path(tpath).read_text().splitlines()]
        self.assertEqual(len(art.results), 3)
        # One 429 happened and the runner retried past it: every variant
        # produced a decision, and transport saw > 6 calls.
        self.assertGreater(transport.calls["n"], 6)
        for entry, case in zip(art.results, cases):
            self.assertFalse(entry["benign"]["malformed"])
            self.assertEqual(entry["benign"]["decision"],
                             case.benign.expected_decision)
            self.assertEqual(entry["benign"]["usage"]["model"], JEV_MODEL)
        self.assertEqual(len(lines), 6)
        self.assertTrue(all("raw" in line for line in lines))

    def test_jev_resume_keeps_dispatch_indices(self):
        cases = _cases(4)
        transport = _jev_transport_factory(cases)
        adapter = JevAdapter(api_key="test", transport=transport)
        half = len(cases) // 2
        prior = [run_case(adapter, cases[i], seed=5, dispatch_base=2 * i)
                 for i in range(half)]
        resumed = run_suite(
            adapter, cases, "trial-demo", "0.1.0-demo", seed=5,
            already_done={cases[i].case_id for i in range(half)},
            prior_results=prior,
        )
        self.assertEqual(len(resumed.results), len(cases))
        for i, entry in enumerate(resumed.results):
            self.assertEqual(entry["benign"]["dispatch_index"], 2 * i)
            self.assertEqual(entry["attacked"]["dispatch_index"], 2 * i + 1)


if __name__ == "__main__":
    unittest.main()
