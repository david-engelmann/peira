"""Phase 0 measurement-primitive tests (2026-09-28 spec).

Covers: budget cap enforcement, cumulative retry/backoff latency,
per-attempt transcript latencies, timeout rate, pricing_version +
model-level confidence (Jev secondary), lock-sealed contract_version,
and explicit cache-state declarations for leaderboard ingestion.

Run with: PYTHONPATH=python python3 -m unittest discover tests
"""

import json
import math
import tempfile
import time
import unittest
from pathlib import Path

from peira.adapters.base import (
    AbstainOutput,
    CallUsage,
    ChoiceOutput,
    ScoreOutput,
)
from peira.artifacts import RunArtifact
from peira.metrics import CallRecord, PerCaseResult
from peira.runner import load_cases, run_suite
from peira.runs_registry import qualifies_for_leaderboard

REPO_ROOT = Path(__file__).resolve().parents[1]


def _usage(tokens_in=1000, tokens_out=500):
    return CallUsage(
        model="gpt-5.6-sol",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=1.0,
        cost_usd=0.0,
    )


def _output_for(primitive, usage):
    if primitive == "score":
        return ScoreOutput(score=0.8, decision="approve", confidence=0.9,
                           usage=usage)
    if primitive == "abstain":
        return AbstainOutput(decision="", abstained=True,
                             refusal_reason="test", usage=usage)
    return ChoiceOutput(decision="approve", confidence=0.9, usage=usage)


class PricedAdapter:
    """Deterministic adapter reporting priced usage (gpt-5.6-sol)."""

    name = "priced-test"
    version = "1.0"
    supported_primitives = frozenset({"choice", "score", "abstain"})

    def __init__(self, tokens_in=1000, tokens_out=500, delay=0.0):
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.delay = delay
        self.calls = []

    def decide(self, case_input, primitive, context):
        if self.delay:
            time.sleep(self.delay)
        self.calls.append(context.call_id)
        return _output_for(
            primitive, _usage(self.tokens_in, self.tokens_out))


class TieredCostAdapter:
    """First case cheap (probe), every later case expensive.

    The probe case's two arm calls are the only calls that happen while
    the budget gate has no mean, so keying cost off the global call
    counter is deterministic.
    """

    name = "tiered-test"
    version = "1.0"
    supported_primitives = frozenset({"choice", "score", "abstain"})

    def __init__(self):
        self.n_calls = 0

    def decide(self, case_input, primitive, context):
        self.n_calls += 1
        time.sleep(0.01)
        if self.n_calls <= 2:
            tokens_in, tokens_out = 10, 5
        else:
            tokens_in, tokens_out = 10000, 5000
        return _output_for(primitive, _usage(tokens_in, tokens_out))


class UnpricedAdapter:
    """Adapter using a table-missing model: every call prices at 0.0.

    The adapter reports a bogus cost_usd of its own; the runner's cost
    authority must ignore it (unknown models price at 0.0, explicitly
    unaccounted rather than silently estimated).
    """

    name = "unpriced-test"
    version = "1.0"
    supported_primitives = frozenset({"choice", "score", "abstain"})

    def decide(self, case_input, primitive, context):
        usage = CallUsage(
            model="no-such-model-in-table", tokens_in=1000, tokens_out=500,
            latency_ms=1.0, cost_usd=99.99,
        )
        return _output_for(primitive, usage)


class TimeoutAdapter:
    """Raises TimeoutError the first `fail_times` calls, then succeeds."""

    name = "timeout-test"
    version = "1.0"
    supported_primitives = frozenset({"choice", "score", "abstain"})

    def __init__(self, fail_times=1, fail_with=TimeoutError):
        self.fail_times = fail_times
        self.fail_with = fail_with
        self.n_calls = 0

    def decide(self, case_input, primitive, context):
        self.n_calls += 1
        if self.n_calls <= self.fail_times:
            raise self.fail_with("simulated timeout")
        return _output_for(primitive, _usage(10, 5))


def _cases(n=4):
    return load_cases(REPO_ROOT / "dataset" / "trial-demo")[:n]


def _rec(**kw):
    base = dict(decision="approve", confidence=0.9, abstained=False,
                refusal_reason="", usage=None, seed=0, dispatch_index=0,
                malformed=False)
    base.update(kw)
    return CallRecord(**base)


def _r(case_id="c1", **kw):
    benign_kw = {k[7:]: v for k, v in kw.items() if k.startswith("benign_")}
    attacked_kw = {k[9:]: v for k, v in kw.items() if k.startswith("attacked_")}
    rest = {k: v for k, v in kw.items()
            if not (k.startswith("benign_") or k.startswith("attacked_"))}
    base = dict(case_id=case_id, family="f", severity="high",
                primitive="choice",
                benign=_rec(**benign_kw), attacked=_rec(**attacked_kw),
                flipped=False, eligible=True, ineligibility_reason="")
    base.update(rest)
    return PerCaseResult(**base)


def _artifact(**over):
    from peira.artifacts import results_to_dicts
    a = RunArtifact(
        adapter_name="mock",
        adapter_version="1",
        suite="trial-demo",
        dataset_version="0.1.0-demo",
        manifest_sha256="abc123",
        results=results_to_dicts([_r("c1")]),
    )
    for k, v in over.items():
        setattr(a, k, v)
    return a.seal()


# ---------------------------------------------------------------------------
# Pricing version + confidence
# ---------------------------------------------------------------------------

class TestPricingConfidence(unittest.TestCase):
    def test_pricing_version_present(self):
        import peira.pricing as p
        table = p.load_pricing_table()
        self.assertEqual(table["pricing_version"], "2026-09-25.1")

    def test_pricing_version_required(self):
        import peira.pricing as p
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as f:
            json.dump({"models": {"m": {"input": 1.0, "output": 2.0,
                                        "confidence": "official"}}}, f)
            path = f.name
        old = p._TABLE_PATH
        p.load_pricing_table.cache_clear()
        try:
            p._TABLE_PATH = Path(path)
            with self.assertRaisesRegex(RuntimeError, "pricing_version"):
                p.load_pricing_table()
        finally:
            p._TABLE_PATH = old
            p.load_pricing_table.cache_clear()
            Path(path).unlink()

    def test_bad_confidence_rejected(self):
        import peira.pricing as p
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as f:
            json.dump({"pricing_version": "x",
                       "models": {"m": {"input": 1.0, "output": 2.0,
                                        "confidence": "rumor"}}}, f)
            path = f.name
        old = p._TABLE_PATH
        p.load_pricing_table.cache_clear()
        try:
            p._TABLE_PATH = Path(path)
            with self.assertRaisesRegex(RuntimeError, "confidence"):
                p.load_pricing_table()
        finally:
            p._TABLE_PATH = old
            p.load_pricing_table.cache_clear()
            Path(path).unlink()

    def test_all_entries_have_confidence(self):
        import peira.pricing as p
        table = p.load_pricing_table()
        for model, entry in table["models"].items():
            self.assertIn(entry.get("confidence"), ("official", "secondary"),
                          f"model {model} missing confidence")

    def test_jev_is_secondary(self):
        import peira.pricing as p
        self.assertEqual(p.pricing_confidence("jev-1.13.0"), "secondary")

    def test_pricing_confidence_helper(self):
        import peira.pricing as p
        self.assertEqual(p.pricing_confidence("gpt-5.6-sol"), "official")
        self.assertIsNone(p.pricing_confidence("no-such-model"))


# ---------------------------------------------------------------------------
# Budget validation
# ---------------------------------------------------------------------------

class TestBudgetValidation(unittest.TestCase):
    def test_zero_rejected(self):
        with self.assertRaisesRegex(ValueError, "budget_usd must be > 0"):
            run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo",
                      budget_usd=0.0)

    def test_negative_rejected(self):
        with self.assertRaisesRegex(ValueError, "budget_usd must be > 0"):
            run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo",
                      budget_usd=-5.0)

    def test_nan_rejected(self):
        with self.assertRaisesRegex(ValueError, "budget_usd must be > 0"):
            run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo",
                      budget_usd=math.nan)

    def test_inf_rejected(self):
        with self.assertRaisesRegex(ValueError, "budget_usd must be > 0"):
            run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo",
                      budget_usd=math.inf)

    def test_bool_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be a number"):
            run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo",
                      budget_usd=True)

    def test_none_ok(self):
        a = run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo",
                      budget_usd=None)
        self.assertIsNone(a.budget_usd)
        self.assertEqual(a.termination, "complete")


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------

class TestBudgetEnforcement(unittest.TestCase):
    def test_cold_start_probe_then_stop(self):
        # gpt-5.6-sol: (1000*4 + 500*20)/1e6 = $0.014/call, $0.028/case.
        # $0.05 covers the probe; projection $0.028 + $0.028*1.5 = $0.07
        # exceeds it, so dispatch stops after the probe.
        a = run_suite(PricedAdapter(), _cases(4), "trial-demo", "0.1.0-demo",
                      budget_usd=0.05, max_concurrency=2)
        self.assertEqual(a.termination, "budget")
        self.assertEqual(a.cases_completed, 1)
        self.assertEqual(a.cases_planned, 4)
        self.assertEqual(a.budget_usd, 0.05)
        self.assertAlmostEqual(a.spent_usd, 0.028, places=6)

    def test_drain_inflight_never_kills_paid_call(self):
        # Probe is cheap; the next two cases are expensive. The gate trips
        # when the first expensive case lands while the second is still
        # in flight: both must complete (no killed paid calls).
        a = run_suite(TieredCostAdapter(), _cases(6), "trial-demo",
                      "0.1.0-demo", budget_usd=0.01, max_concurrency=2)
        self.assertEqual(a.termination, "budget")
        self.assertEqual(a.cases_completed, 3)
        self.assertEqual(a.cases_planned, 6)
        # Every completed case has both arm records with priced usage:
        # no half-finished case survived the drain.
        for entry in a.results:
            for arm in ("benign", "attacked"):
                rec = entry[arm]
                self.assertFalse(rec["malformed"], arm)
                self.assertGreater(rec["usage"]["cost_usd"], 0)
        self.assertGreater(a.spent_usd, a.budget_usd)  # one-case overshoot

    def test_generous_budget_completes(self):
        a = run_suite(PricedAdapter(), _cases(4), "trial-demo", "0.1.0-demo",
                      budget_usd=10.0)
        self.assertEqual(a.termination, "complete")
        self.assertEqual(a.cases_completed, 4)
        self.assertEqual(a.cases_planned, 4)
        self.assertAlmostEqual(a.spent_usd, 4 * 0.028, places=6)

    def test_budget_artifact_never_ranks(self):
        a = run_suite(PricedAdapter(), _cases(4), "trial-demo", "0.1.0-demo",
                      budget_usd=0.05)
        self.assertFalse(a.metrics["ranking_eligible"])
        ok, _reason = qualifies_for_leaderboard(a)
        self.assertFalse(ok)


# ---------------------------------------------------------------------------
# Budget with unpriced calls: counted, never priced
# ---------------------------------------------------------------------------

class TestUnpricedBudget(unittest.TestCase):
    def test_spent_usd_zero_calls_counted(self):
        # Unpriced calls contribute 0.0 to spent_usd but are counted:
        # the adapter's own cost claim is ignored by the runner, and the
        # budget gate never trips on spend it cannot measure.
        a = run_suite(UnpricedAdapter(), _cases(4), "trial-demo",
                      "0.1.0-demo", budget_usd=0.001)
        self.assertEqual(a.termination, "complete")
        self.assertEqual(a.cases_completed, 4)
        self.assertEqual(a.cases_planned, 4)
        self.assertEqual(a.spent_usd, 0.0)
        for entry in a.results:
            for arm in ("benign", "attacked"):
                self.assertEqual(entry[arm]["usage"]["cost_usd"], 0.0)
        cost = a.metrics["cost"]
        self.assertEqual(cost["n_unpriced"], 8)
        self.assertEqual(cost["n_priced"], 0)
        self.assertFalse(cost["sufficient"])
        # Unknown cost is not zero cost: the headline is withheld,
        # never reported as $0.00.
        self.assertIsNone(cost["total_cost_usd"])
        self.assertIsNone(cost["cost_per_1k_decisions"])

    def test_unpriced_run_keeps_termination_complete(self):
        # Unpriced spend never degrades the run's termination state: the
        # gate only binds priced spend, so the run seals complete (its
        # ranking eligibility still fails on the demo suite's coverage
        # floor, which is unrelated to cost).
        a = run_suite(UnpricedAdapter(), _cases(2), "trial-demo",
                      "0.1.0-demo", budget_usd=0.001)
        self.assertEqual(a.termination, "complete")
        reasons = " ".join(a.metrics["eligibility_notes"])
        self.assertNotIn("terminated early", reasons)
        self.assertIsNone(a.metrics["cost"]["total_cost_usd"])


# ---------------------------------------------------------------------------
# Cumulative latency
# ---------------------------------------------------------------------------

class TestCumulativeLatency(unittest.TestCase):
    def test_single_attempt_total_matches_attempt(self):
        a = run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo",
                      max_attempts=1)
        rec = a.results[0]["benign"]
        self.assertAlmostEqual(rec["latency_ms_total"],
                               rec["usage"]["latency_ms"], delta=5.0)

    def test_retry_accumulates_backoff(self):
        # First call times out (retryable), second succeeds: the total
        # covers both attempts plus the backoff sleep between them.
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td) / "t.jsonl"
            a = run_suite(TimeoutAdapter(fail_times=1), _cases(1),
                          "trial-demo", "0.1.0-demo",
                          max_attempts=2, transcript_path=tp)
            entries = [json.loads(line)
                       for line in tp.read_text().splitlines()]
        rec = a.results[0]["benign"]
        self.assertFalse(rec["timed_out"])
        self.assertFalse(rec["malformed"])
        benign_entries = [e for e in entries if e["variant"] == "benign"]
        self.assertEqual(len(benign_entries), 1)
        attempt_lat = benign_entries[0]["attempt_latencies_ms"]
        self.assertEqual(len(attempt_lat), 2)
        # Total >= sum of attempts (plus backoff); >= final attempt.
        self.assertGreaterEqual(rec["latency_ms_total"],
                                sum(attempt_lat) - 1.0)
        self.assertGreaterEqual(rec["latency_ms_total"],
                                rec["usage"]["latency_ms"])

    def test_transcript_attempt_latencies_match_attempts(self):
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td) / "t.jsonl"
            run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo",
                      max_attempts=1, transcript_path=tp)
            entries = [json.loads(line)
                       for line in tp.read_text().splitlines()]
        for e in entries:
            self.assertEqual(len(e["attempt_latencies_ms"]), e["attempts"])
            self.assertGreaterEqual(e["latency_ms_total"],
                                    sum(e["attempt_latencies_ms"]) - 1.0)


# ---------------------------------------------------------------------------
# Timeout accounting
# ---------------------------------------------------------------------------

class TestTimeoutAccounting(unittest.TestCase):
    def test_terminal_timeout_flagged(self):
        a = run_suite(TimeoutAdapter(fail_times=99), _cases(2),
                      "trial-demo", "0.1.0-demo", max_attempts=1)
        for entry in a.results:
            for arm in ("benign", "attacked"):
                rec = entry[arm]
                self.assertTrue(rec["timed_out"], arm)
                self.assertTrue(rec["malformed"], arm)
                self.assertIsNone(rec["usage"])
        m = a.metrics
        for key in ("benign", "attacked", "overall"):
            self.assertEqual(m["latency_ms"][key]["timeout_rate"], 1.0)
        self.assertEqual(m["latency_ms"]["benign"]["n_timeouts"], 2)
        self.assertEqual(m["latency_ms"]["attacked"]["n_timeouts"], 2)
        self.assertEqual(m["latency_ms"]["overall"]["n_timeouts"], 4)

    def test_retry_then_success_not_timed_out(self):
        a = run_suite(TimeoutAdapter(fail_times=1), _cases(1),
                      "trial-demo", "0.1.0-demo", max_attempts=3)
        rec = a.results[0]["benign"]
        self.assertFalse(rec["timed_out"])
        self.assertFalse(rec["malformed"])

    def test_non_timeout_error_not_flagged(self):
        a = run_suite(TimeoutAdapter(fail_times=99, fail_with=ValueError),
                      _cases(1), "trial-demo", "0.1.0-demo", max_attempts=1)
        rec = a.results[0]["benign"]
        self.assertFalse(rec["timed_out"])
        self.assertTrue(rec["malformed"])

    def test_timeout_rate_zero_reported(self):
        a = run_suite(PricedAdapter(), _cases(2), "trial-demo", "0.1.0-demo")
        for key in ("benign", "attacked", "overall"):
            self.assertIn("timeout_rate", a.metrics["latency_ms"][key])
            self.assertEqual(a.metrics["latency_ms"][key]["timeout_rate"], 0.0)

    def test_timeout_rate_unit(self):
        # Unit-level: timeout_rate sits beside p50/p95/p99 and timeouts
        # never enter the percentile inputs.
        from peira.metrics import latency_summary
        ok_usage = CallUsage(model="m", tokens_in=1, tokens_out=1,
                             latency_ms=100.0, cost_usd=0.0)
        ok = _r("c1",
                benign_usage=ok_usage, benign_latency_ms_total=100.0,
                attacked_malformed=True, attacked_usage=None,
                attacked_timed_out=True, attacked_latency_ms_total=1000.0)
        s = latency_summary([ok])
        self.assertEqual(s["benign"]["timeout_rate"], 0.0)
        self.assertEqual(s["benign"]["n_timeouts"], 0)
        self.assertEqual(s["attacked"]["timeout_rate"], 1.0)
        self.assertEqual(s["attacked"]["n_timeouts"], 1)
        self.assertEqual(s["overall"]["timeout_rate"], 0.5)
        self.assertEqual(s["overall"]["n_timeouts"], 1)
        # The timeout's 1000ms never enters the percentile inputs: only
        # the one good call counts (percentiles themselves are withheld
        # below 30 observations).
        self.assertEqual(s["benign"]["n"], 1)
        self.assertEqual(s["attacked"]["n"], 0)
        self.assertEqual(s["overall"]["n"], 1)


# ---------------------------------------------------------------------------
# Artifact contract
# ---------------------------------------------------------------------------

class TestArtifactContract(unittest.TestCase):
    def test_contract_version_sealed(self):
        a = run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo")
        self.assertEqual(a.contract_version, "1")
        d = json.loads(a.to_json())
        self.assertEqual(d["contract_version"], "1")

    def test_contract_version_lock_covered(self):
        a = run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo")
        d = json.loads(a.to_json())
        b = RunArtifact.from_json(json.dumps(d))
        self.assertTrue(b.verify())
        b.contract_version = "999"
        self.assertFalse(b.verify())

    def test_termination_lock_covered(self):
        a = run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo")
        d = json.loads(a.to_json())
        b = RunArtifact.from_json(json.dumps(d))
        self.assertTrue(b.verify())
        b.termination = "budget"
        self.assertFalse(b.verify())

    def test_budget_fields_round_trip(self):
        a = _artifact(budget_usd=5.0, spent_usd=1.25, termination="budget",
                      cases_completed=3, cases_planned=10)
        d = json.loads(a.to_json())
        b = RunArtifact.from_json(json.dumps(d))
        self.assertEqual(b.budget_usd, 5.0)
        self.assertEqual(b.spent_usd, 1.25)
        self.assertEqual(b.termination, "budget")
        self.assertEqual(b.cases_completed, 3)
        self.assertEqual(b.cases_planned, 10)

    def test_budget_usd_bad_types_rejected(self):
        a = _artifact()
        d = json.loads(a.to_json())
        for bad in ("x", True, [1]):
            d2 = dict(d)
            d2["budget_usd"] = bad
            with self.assertRaises(ValueError, msg=f"budget_usd={bad!r}"):
                RunArtifact.from_json(json.dumps(d2))

    def test_call_record_new_fields(self):
        a = _artifact()
        d = json.loads(a.to_json())
        rec = d["results"][0]["benign"]
        rec["latency_ms_total"] = 123.0
        rec["timed_out"] = True
        rec["cached"] = True
        b = RunArtifact.from_json(json.dumps(d))
        got = b.results[0]["benign"]
        self.assertEqual(got["latency_ms_total"], 123.0)
        self.assertTrue(got["timed_out"])
        self.assertTrue(got["cached"])

    def test_call_record_new_field_bad_types(self):
        a = _artifact()
        d = json.loads(a.to_json())
        rec = d["results"][0]["benign"]
        for field, bad in (("latency_ms_total", -1.0),
                           ("latency_ms_total", "x"),
                           ("timed_out", 1),
                           ("cached", "yes")):
            d2 = json.loads(json.dumps(d))
            d2["results"][0]["benign"][field] = bad
            with self.assertRaises(ValueError, msg=f"{field}={bad!r}"):
                RunArtifact.from_json(json.dumps(d2))

    def test_pricing_version_sealed(self):
        a = run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo")
        self.assertEqual(a.pricing_version, "2026-09-25.1")

    def test_pricing_version_lock_covered(self):
        a = run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo")
        d = json.loads(a.to_json())
        b = RunArtifact.from_json(json.dumps(d))
        self.assertTrue(b.verify())
        b.pricing_version = "1999-01-01.9"
        self.assertFalse(b.verify())

    def test_cache_flag_lock_covered(self):
        a = run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo")
        self.assertFalse(a.config["cache_enabled"])
        d = json.loads(a.to_json())
        b = RunArtifact.from_json(json.dumps(d))
        self.assertTrue(b.verify())
        b.config["cache_enabled"] = True
        self.assertFalse(b.verify())


# ---------------------------------------------------------------------------
# Cache state declaration
# ---------------------------------------------------------------------------

class TestCacheState(unittest.TestCase):
    def test_cache_enabled_declared_true_with_dir(self):
        with tempfile.TemporaryDirectory() as td:
            a = run_suite(PricedAdapter(), _cases(1), "trial-demo",
                          "0.1.0-demo", cache_dir=td)
        self.assertTrue(a.config["cache_enabled"])

    def test_cache_enabled_declared_false_without_dir(self):
        a = run_suite(PricedAdapter(), _cases(1), "trial-demo", "0.1.0-demo")
        self.assertFalse(a.config["cache_enabled"])

    def test_registry_rejects_undeclared_cache(self):
        a = _artifact()
        # Built via the constructor (not the runner): cache_enabled is
        # absent, which is exactly the undeclared state.
        self.assertNotIn("cache_enabled", a.config)
        ok, _reason = qualifies_for_leaderboard(a)
        self.assertFalse(ok)

    def test_registry_rejects_non_bool_cache(self):
        a = _artifact()
        a.config["cache_enabled"] = "yes"
        a = a.seal()
        ok, _reason = qualifies_for_leaderboard(a)
        self.assertFalse(ok)

    def test_registry_rejects_budget_termination(self):
        a = _artifact(termination="budget", cases_completed=1,
                      cases_planned=4)
        ok, _reason = qualifies_for_leaderboard(a)
        self.assertFalse(ok)

    def test_registry_rejects_partial_termination(self):
        a = _artifact(termination="partial")
        ok, _reason = qualifies_for_leaderboard(a)
        self.assertFalse(ok)

    def test_registry_accepts_complete_declared(self):
        a = _artifact()
        a.config["cache_enabled"] = False
        a.metrics["ranking_eligible"] = True
        a = a.seal()
        ok, _reason = qualifies_for_leaderboard(a)
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# Resume validation (budget / pricing / contract / cache)
# ---------------------------------------------------------------------------

class TestResumeValidation(unittest.TestCase):
    def _partial(self, **over):
        from peira.artifacts import results_to_dicts
        from peira.pricing import load_pricing_table
        case_id = _cases(4)[0].case_id
        a = RunArtifact(
            adapter_name=PricedAdapter.name,
            adapter_version=PricedAdapter.version,
            suite="trial-demo",
            dataset_version="0.1.0-demo",
            manifest_sha256="abc123",
            termination="partial",
            pricing_version=load_pricing_table()["pricing_version"],
            budget_usd=5.0,
            spent_usd=0.028,
            cases_completed=1,
            cases_planned=4,
            results=results_to_dicts([_r(case_id)]),
        )
        a.config["cache_enabled"] = False
        for k, v in over.items():
            if k == "cache_enabled":
                a.config["cache_enabled"] = v
            else:
                setattr(a, k, v)
        return a.seal()

    def _validate(self, partial, **kw):
        from peira.runner import validate_partial
        args = dict(budget_usd=5.0, cache_enabled=False)
        args.update(kw)
        return validate_partial(
            partial, PricedAdapter(), _cases(4), "trial-demo", "0.1.0-demo",
            "abc123", seed=0, **args)

    def test_resume_accepts_matching(self):
        done, prior = self._validate(self._partial())
        self.assertEqual(done, {_cases(4)[0].case_id})

    def test_resume_rejects_budget_mismatch(self):
        with self.assertRaisesRegex(ValueError, "budget_usd"):
            self._validate(self._partial(), budget_usd=10.0)

    def test_resume_rejects_cache_mismatch(self):
        with self.assertRaisesRegex(ValueError, "cache_enabled"):
            self._validate(self._partial(), cache_enabled=True)

    def test_resume_rejects_undeclared_cache(self):
        p = self._partial()
        del p.config["cache_enabled"]
        p = p.seal()
        with self.assertRaisesRegex(ValueError, "cache state"):
            self._validate(p)

    def test_resume_rejects_pricing_mismatch(self):
        with self.assertRaisesRegex(ValueError, "pricing_version"):
            self._validate(self._partial(pricing_version="1999-01-01.9"))

    def test_resume_rejects_contract_mismatch(self):
        with self.assertRaisesRegex(ValueError, "contract_version"):
            self._validate(self._partial(contract_version="999"))


# ---------------------------------------------------------------------------
# CLI budget flag
# ---------------------------------------------------------------------------
class TestCliBudget(unittest.TestCase):
    def test_budget_usd_flag_parses(self):
        from peira.cli import build_parser
        args = build_parser().parse_args(
            ["run", "--budget-usd", "5.0"])
        self.assertEqual(args.budget_usd, 5.0)
        args = build_parser().parse_args(["run"])
        self.assertIsNone(args.budget_usd)

    def test_budget_usd_nonpositive_rejected(self):
        from peira.cli import build_parser, cmd_run, EXIT_USER_ERROR
        for bad in ("0", "-3"):
            args = build_parser().parse_args(
                ["run", "--adapter", "mock", "--suite", "trial-demo",
                 "--budget-usd", bad, "--dry-run"])
            self.assertEqual(cmd_run(args), EXIT_USER_ERROR,
                             f"budget {bad} should be rejected")

    def test_budget_usd_nan_rejected(self):
        from peira.cli import build_parser, cmd_run, EXIT_USER_ERROR
        args = build_parser().parse_args(
            ["run", "--adapter", "mock", "--suite", "trial-demo",
             "--budget-usd", "nan", "--dry-run"])
        self.assertEqual(cmd_run(args), EXIT_USER_ERROR)


# ---------------------------------------------------------------------------
# Pre-run budget estimate note
# ---------------------------------------------------------------------------

class TestBudgetEstimateNote(unittest.TestCase):
    def _note(self, out_dir, slug, suite, budget_usd, n_remaining):
        from peira.cli import _budget_estimate_note
        return _budget_estimate_note(
            out_dir, slug, suite, budget_usd, n_remaining)

    def test_no_history_note(self):
        with tempfile.TemporaryDirectory() as td:
            note = self._note(Path(td), "mock-adapter", "trial-demo",
                              5.0, 100)
        self.assertIn("budget: $5.00 cap", note)
        self.assertIn("no priced cost history", note)
        self.assertIn("projection: spent + mean x 1.5", note)

    def test_unreadable_history_note(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "mock-adapter-trial-demo.json").write_text("not json")
            note = self._note(d, "mock-adapter", "trial-demo", 5.0, 100)
        self.assertIn("no priced cost history", note)

    def test_zero_spent_history_note(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "mock-adapter-trial-demo.json").write_text(json.dumps(
                {"spent_usd": 0.0, "cases_completed": 10}))
            note = self._note(d, "mock-adapter", "trial-demo", 5.0, 100)
        self.assertIn("no priced cost history", note)

    def test_history_note_covers_run(self):
        # Prior final artifact: $0.28 over 10 cases = $0.028/case.
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "mock-adapter-trial-demo.json").write_text(json.dumps(
                {"spent_usd": 0.28, "cases_completed": 10}))
            note = self._note(d, "mock-adapter", "trial-demo", 5.0, 100)
        self.assertIn("~$0.0280/case", note)
        self.assertIn("~$2.80 for 100 remaining cases", note)
        self.assertIn("covers the run", note)
        self.assertIn("~178 cases covered", note)

    def test_history_note_short(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "mock-adapter-trial-demo.json").write_text(json.dumps(
                {"spent_usd": 0.28, "cases_completed": 10}))
            note = self._note(d, "mock-adapter", "trial-demo", 1.0, 100)
        self.assertIn("short by ~$1.80", note)

    def test_partial_and_replay_artifacts_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for suffix in (".partial.json", ".replay.json"):
                (d / f"mock-adapter-trial-demo{suffix}").write_text(
                    json.dumps({"spent_usd": 99.0, "cases_completed": 1}))
            note = self._note(d, "mock-adapter", "trial-demo", 5.0, 100)
        # Checkpoint and replay files are not cost history: the note must
        # not price off them.
        self.assertIn("no priced cost history", note)


if __name__ == "__main__":
    unittest.main()
